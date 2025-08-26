import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional

# --- Import our new, separated flow handlers ---
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.outofscope_flow import handle_out_of_scope

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- Define AI Models (Centralized) ---
gatekeeper_model = genai.GenerativeModel('gemini-1.5-flash-latest')
factual_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
ranking_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models (Centralized) ---
class ChatMessage(BaseModel):
    role: str
    content: str

class UserQuery(BaseModel):
    history: List[ChatMessage]
    applied_filters: Optional[dict] = Field(None, description="The filters that were successfully applied in the previous turn.")
    candidate_pool: Optional[List[dict]] = Field(None, description="The full list of candidates from the initial semantic search.")
    booking_context: Optional[dict] = Field(None, description="Context for an ongoing booking process.")

# --- Gatekeeper Intent Definitions ---
class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    OUT_OF_SCOPE = "out_of_scope"

class GatekeeperDecision(BaseModel):
    intent: ChatIntent

# --- FastAPI App ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    if not query.history:
        return {"response": "Error: History is empty."}
    
    # --- Centralized State Management ---
    latest_user_message = query.history[-1].content
    previous_filters = query.applied_filters or {}
    candidate_clinics = query.candidate_pool or []
    booking_context = query.booking_context or {}
    
    conversation_history_for_prompt = ""
    for msg in query.history:
        conversation_history_for_prompt += f"{msg.role}: {msg.content}\n"

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")

    # --- STAGE 1: THE GATEKEEPER ---
        # --- STAGE 1: THE GATEKEEPER ---
    intent = ChatIntent.FIND_CLINIC # Default intent
    try:
        gatekeeper_prompt = f"""
        You are an expert Gatekeeper AI for a dental concierge. Your only job is to classify the user's intent into one of four categories based on their most recent message. Respond with only the function call.

        Here are your categories and examples:
        1. 'find_clinic': The user is asking to find, locate, or get recommendations for a dental clinic.
            - "find me a clinic for crowns in JB"
            - "which is the most affordable option?"
            - "any clinics near permas jaya"

        2. 'book_appointment': The user is asking to book, schedule, or make an appointment.
            - "I'd like to book at Q&M Dental"
            - "can I make an appointment?"

        3. 'general_dental_question': The user is asking a general question about dental health, procedures, or costs.
            - "what is a root canal?"
            - "do veneers hurt?"
            - "how much is scaling?"

        4. 'out_of_scope': The query is not related to dentistry at all. This includes greetings, travel questions, weather, or random statements.
            - "how are you doing today?"
            - "what's the weather like?"
            - "how to get to the clinic?"

        Analyze the user's most recent message from the conversation below and classify it.

        ---
        User conversation history:
        {conversation_history_for_prompt}
        ---
        """
        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        function_call = gatekeeper_response.candidates[0].content.parts[0].function_call
        if function_call and function_call.args:
            intent = function_call.args['intent']
        print(f"Gatekeeper decided intent is: {intent}")
    except Exception as e:
        print(f"Gatekeeper Error: {e}. Defaulting to find_clinic.")

    # --- STAGE 2: THE ROUTER ---
    # Based on the intent, call the appropriate specialist handler.
    
    response_data = {}

    if intent == ChatIntent.FIND_CLINIC:
        # Pass all necessary tools and state to the find_clinic handler
        response_data = handle_find_clinic(latest_user_message, previous_filters, candidate_clinics, factual_brain_model, ranking_brain_model, embedding_model, generation_model, supabase)
    
    elif intent == ChatIntent.BOOK_APPOINTMENT:
        # Pass all necessary tools and state to the booking handler
        response_data = handle_booking_flow(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)

    elif intent == ChatIntent.GENERAL_DENTAL_QUESTION:
        response_data = handle_qna(latest_user_message, generation_model)
        # Preserve the user's previous search context in case they ask to find a clinic next
        response_data["applied_filters"] = previous_filters
        response_data["candidate_pool"] = candidate_clinics
        response_data["booking_context"] = booking_context

    elif intent == ChatIntent.OUT_OF_SCOPE:
        response_data = handle_out_of_scope(latest_user_message)
        # Preserve the user's previous search context
        response_data["applied_filters"] = previous_filters
        response_data["candidate_pool"] = candidate_clinics
        response_data["booking_context"] = booking_context

    else:
        # A final safety net
        response_data = {"response": "I'm sorry, I encountered an unexpected error."}

    return response_data