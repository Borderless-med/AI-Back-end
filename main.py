import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional

# --- Import all four of our new, separated flow handlers ---
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
gatekeeper_model = genai.GenerativeModel('gemini-1.5-flash-001')
factual_brain_model = genai.GenerativeModel('gemini-1.5-flash-001')
ranking_brain_model = genai.GenerativeModel('gemini-1.5-flash-001')
embedding_model = 'models/embedding-001' # This model is already versioned, no change needed.
generation_model = genai.GenerativeModel('gemini-1.5-flash-001')

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

RESET_KEYWORDS = [
    "never mind", "start over", "reset", "restart", "reboot", "forget that", "forget all that",
    "clear filters", "let's try that again", "take two", "start from the top", "do-over",
    "change the subject", "new topic", "new search", "change course", "new direction",
    "switch gears", "let's pivot", "about face", "u-turn", "take another tack", "clean slate",
    "wipe the slate clean", "blank canvas", "empty page", "clean sheet", "back to square one",
    "back to the drawing board", "new chapter", "fresh chapter", "actually", "how about something else",
]

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
   
    if not query.history:
        return {"response": "Error: History is empty."}
    
    # --- Centralized State Management ---
    latest_user_message = query.history[-1].content.lower()
    previous_filters = query.applied_filters or {}
    candidate_clinics = query.candidate_pool or []
    booking_context = query.booking_context or {}
    
    conversation_history_for_prompt = ""
    for msg in query.history:
        conversation_history_for_prompt += f"{msg.role}: {msg.content}\n"

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")

    # --- STAGE 1: THE INTELLIGENT GATEKEEPER ---
    intent = ChatIntent.FIND_CLINIC
    try:
               
        gatekeeper_prompt = f"""
        You are an expert intent classification AI. Your only job is to analyze the user's message and call the `GatekeeperDecision` tool with the correct classification. You must not respond in any other way.

        **Decision Logic:**
        - `find_clinic`: User is asking for a clinic, describing a dental need, or asking for the "best" or a "good" clinic. EXAMPLES: "I need a filling," "find clinics for braces," "what are the best clinics in JB".
        - `book_appointment`: User is explicitly asking to schedule, reserve a time, or make an appointment. EXAMPLES: "I want to book an appointment," "can I schedule a visit?".
        - `general_dental_question`: User is asking a general knowledge question about dentistry. EXAMPLES: "what is a root canal?", "do veneers hurt?".
        - `out_of_scope`: The query is a simple greeting, a test message, a thank you, small talk, or is clearly not about dentistry. EXAMPLES: "hello", "test", "how are you", "how to get to...", "what is the weather".

        **CRITICAL INSTRUCTION:** Read the user's most recent message. Find the BEST match from the four intents above and call the `GatekeeperDecision` tool with that intent. THIS IS YOUR ONLY TASK. DO NOT FAIL.

        Conversation History:
        {conversation_history_for_prompt}

        User's MOST RECENT message is: "{latest_user_message}"
        """
        # (Inside your @app.post("/chat") function in main.py)

        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        
        part = gatekeeper_response.candidates[0].content.parts[0]
        if hasattr(part, 'function_call') and part.function_call.args:
            intent = part.function_call.args['intent']
            print(f"Gatekeeper decided intent is: {intent}")
        else:
            print(f"Gatekeeper Error: AI did not return a valid function call. Raw response: {gatekeeper_response.text}")
            intent = ChatIntent.FIND_CLINIC

    except Exception as e:
        print(f"Gatekeeper Exception: An exception occurred: {e}")
        intent = ChatIntent.FIND_CLINIC

    # --- STAGE 2: THE ROUTER ---
    response_data = {}

    if intent == ChatIntent.FIND_CLINIC:
        # --- THIS IS THE UPGRADED CALL WITH THE NEW CONTEXT-AWARE PROMPT ---
        response_data = handle_find_clinic(
            latest_user_message=latest_user_message,
            conversation_history=conversation_history_for_prompt, # Pass the history
            previous_filters=previous_filters,
            candidate_clinics=candidate_clinics,
            factual_brain_model=factual_brain_model,
            ranking_brain_model=ranking_brain_model,
            embedding_model=embedding_model,
            generation_model=generation_model,
            supabase=supabase,
            RESET_KEYWORDS=RESET_KEYWORDS
        )
    
    elif intent == ChatIntent.BOOK_APPOINTMENT:
        response_data = handle_booking_flow(
            latest_user_message=latest_user_message,
            booking_context=booking_context,
            previous_filters=previous_filters,
            candidate_clinics=candidate_clinics,
            factual_brain_model=factual_brain_model
        )

    elif intent == ChatIntent.GENERAL_DENTAL_QUESTION:
        response_data = handle_qna(
            latest_user_message=latest_user_message,
            generation_model=generation_model
        )
        response_data["applied_filters"] = previous_filters
        response_data["candidate_pool"] = candidate_clinics
        response_data["booking_context"] = booking_context

    elif intent == ChatIntent.OUT_OF_SCOPE:
        response_data = handle_out_of_scope(latest_user_message)
        response_data["applied_filters"] = previous_filters
        response_data["candidate_pool"] = candidate_clinics
        response_data["booking_context"] = booking_context

    else:
        response_data = {"response": "I'm sorry, I encountered an unexpected error."}

    return response_data