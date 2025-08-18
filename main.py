import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional, Any
import json
import numpy as np
from numpy.linalg import norm
from urllib.parse import urlencode

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- AI Models ---
gatekeeper_model = genai.GenerativeModel('gemini-1.5-flash-latest') # NEW
factual_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
ranking_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class ChatMessage(BaseModel):
    role: str
    content: str

class UserQuery(BaseModel):
    history: List[ChatMessage]
    applied_filters: Optional[dict] = Field(None, description="The filters that were successfully applied in the previous turn.")
    candidate_pool: Optional[List[dict]] = Field(None, description="The full list of candidates from the initial semantic search.")
    booking_context: Optional[dict] = Field(None, description="Context for an ongoing booking process.")

class ServiceEnum(str, Enum):
    # ... (Enum values are unchanged)
    pass

class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

class BookingIntent(BaseModel):
    """Triggers when the user expresses a clear intent to book an appointment for a specific clinic."""
    clinic_name: str = Field(..., description="The name of the dental clinic the user wants to book.")

class UserInfo(BaseModel):
    """Captures the user's personal details for pre-filling a booking form."""
    patient_name: str = Field(..., description="The user's full name.")
    email_address: str = Field(..., description="The user's email address.")
    whatsapp_number: str = Field(..., description="The user's WhatsApp number, including country code if provided.")

# NEW: Pydantic model for the Gatekeeper's decision
class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_QUESTION = "general_question"

class GatekeeperDecision(BaseModel):
    """Classifies the user's primary intent."""
    intent: ChatIntent

# --- FastAPI App ---
app = FastAPI()

RESET_KEYWORDS = [
    # ... (Keywords are unchanged)
]

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    if not query.history:
        return {"response": "Error: History is empty."}
    
    latest_user_message = query.history[-1].content.lower()
    previous_filters = query.applied_filters or {}
    candidate_clinics = query.candidate_pool or []
    booking_context = query.booking_context or {}
    
    conversation_history_for_prompt = ""
    for msg in query.history:
        conversation_history_for_prompt += f"{msg.role}: {msg.content}\n"

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")
    print(f"Booking Context: {booking_context}")

    # --- STAGE 0: THE GATEKEEPER ---
    intent = ChatIntent.FIND_CLINIC # Default
    try:
        gatekeeper_prompt = f"Classify the user's intent based on their latest message. History:\n{conversation_history_for_prompt}"
        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        function_call = gatekeeper_response.candidates[0].content.parts[0].function_call
        if function_call and function_call.args:
            intent = function_call.args['intent']
        print(f"Gatekeeper decided intent is: {intent}")
    except Exception as e:
        print(f"Gatekeeper Error: {e}. Defaulting to find_clinic.")

    # --- BOOKING MODE LOGIC ---
    if intent == ChatIntent.BOOK_APPOINTMENT or booking_context.get("status") == "gathering_info":
        # ... (The entire booking mode logic from the previous file goes here)
        # ... (This logic is now self-contained and only runs when the intent is correct)
        # For brevity, this is a placeholder. The full code is in the version I will send next.
        pass

    # --- RECOMMENDATION MODE ---
    elif intent == ChatIntent.FIND_CLINIC:
        # ... (The entire recommendation mode logic from the previous file goes here)
        # ... (This logic is now self-contained and only runs when the intent is correct)
        # For brevity, this is a placeholder.
        pass
        
    # --- GENERAL QUESTION MODE (Future) ---
    else:
        return {"response": "Sorry, I can only help with finding or booking dental clinics right now."}

    # This is a placeholder return. I will provide the full, final code next.
    return {"response": "An error occurred."}