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
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

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

    # --- BOOKING MODE LOGIC ---
    if booking_context.get("status") == "gathering_info":
        print("In Booking Mode: Capturing user info...")
        try:
            user_info_response = factual_brain_model.generate_content(
                f"Extract the user's name, email, and WhatsApp number from this message: '{latest_user_message}'",
                tools=[UserInfo]
            )
            function_call = user_info_response.candidates.content.parts.function_call
            if function_call and function_call.args:
                user_args = function_call.args
                base_url = "https://www.sg-jb-dental.com/book-now"
                params = {
                    'name': user_args.get('patient_name'),
                    'email': user_args.get('email_address'),
                    'phone': user_args.get('whatsapp_number'),
                    'clinic': booking_context.get('clinic_name'),
                    'treatment': booking_context.get('treatment')
                }
                params = {k: v for k, v in params.items() if v is not None}
                query_string = urlencode(params)
                final_url = f"{base_url}?{query_string}"
                final_response_text = f"Perfect, thank you! I have pre-filled the booking form for you. Please click this link to choose your preferred date and time, and to confirm your appointment:\n\n[Click here to complete your booking]({final_url})"
                
                return {
                    "response": final_response_text,
                    "applied_filters": {},
                    "candidate_pool": [],
                    "booking_context": {"status": "complete"}
                }
        except Exception as e:
            print(f"Booking Info Capture Error: {e}")
            final_response_text = "I'm sorry, I had trouble understanding those details. Could you please try entering them again? Just your name, email, and WhatsApp number."
            return {
                "response": final_response_text,
                "applied_filters": previous_filters,
                "candidate_pool": candidate_clinics,
                "booking_context": booking_context
            }

    # --- RECOMMENDATION MODE ---
    current_filters = {}
    booking_intent_detected = None
    try:
        tools = [UserIntent, BookingIntent]
        prompt_text = f"Analyze this user query: '{latest_user_message}'. If the user wants to find a clinic, use the UserIntent tool. If the user expresses a desire to book an appointment at a specific clinic visible in the chat history, use the BookingIntent tool."
        factual_response = factual_brain_model.generate_content(prompt_text, tools=tools)
        
        # BUG FIX 1: Robust parsing for Factual Brain
        if factual_response.candidates and factual_response.candidates[0].content.parts:
            function_call = factual_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args:
                if function_call.name == 'BookingIntent':
                    booking_intent_detected = function_call.args
                else: # UserIntent
                    args = function_call.args
                    if args.get('service'): current_filters['services'] = [args.get('service')]
                    if args.get('township'): current_filters['township'] = args.get('township')

        print(f"Factual Brain extracted: {current_filters}")
        if booking_intent_detected: print(f"Booking Intent Detected: {booking_intent_detected}")

    except Exception as e:
        print(f"Factual Brain Error: {e}")

    if booking_intent_detected:
        clinic_name = booking_intent_detected.get('clinic_name')
        treatment = (previous_filters.get('services') or [None])[0]
        new_booking_context = {"status": "gathering_info", "clinic_name": clinic_name, "treatment": treatment}
        response_text = f"Great! I can help you get started with booking an appointment for **{treatment or 'a consultation'}** at **{clinic_name}**. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
        
        return {
            "response": response_text,
            "applied_filters": previous_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": new_booking_context
        }

    final_filters = {}
    user_wants_to_reset = any(keyword in latest_user_message for keyword in RESET_KEYWORDS)

    if user_wants_to_reset:
        print("Deterministic Planner decided: REPLACE (reset keyword found).")
        final_filters = current_filters
        candidate_clinics = []
    else:
        print("Deterministic Planner decided: MERGE (default action).")
        final_filters = previous_filters.copy()
        final_filters.update(current_filters)
    
    print(f"Final Filters to be applied: {final_filters}")

    ranking_priorities = []
    try:
        # Ranking brain logic...
        pass
    except Exception as e:
        print(f"Ranking Brain Error: {e}")

    if not candidate_clinics:
        print("Candidate pool is empty. Performing initial database search.")
        try:
            # Semantic search logic...
            pass
        except Exception as e:
            print(f"Semantic search DB function error: {e}")
    else:
        print(f"Using existing candidate pool of {len(candidate_clinics)} clinics.")

    qualified_clinics = []
    if candidate_clinics:
        # Filtering logic...
        pass

    top_clinics = []
    if qualified_clinics:
        # Ranking logic...
        pass
        
        # BUG FIX 2: Correctly access the list item
        print(f"Ranking complete. Top clinic: {top_clinics[0]['name'] if top_clinics else 'N/A'}")

    context = ""
    if top_clinics:
        # Context generation logic...
        pass
    
    augmented_prompt = f"""
    You are a helpful and expert AI dental concierge... (same as before)
    """
    
    final_response = generation_model.generate_content(augmented_prompt)

    return {
        "response": final_response.text, 
        "applied_filters": final_filters,
        "candidate_pool": candidate_clinics,
        "booking_context": {}
    }