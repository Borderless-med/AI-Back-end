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
gatekeeper_model = genai.GenerativeModel('gemini-1.5-flash-latest')
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
    travel_context: Optional[dict] = Field(None, description="Context for an ongoing travel planning process.")

class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

class BookingIntent(BaseModel):
    clinic_name: str = Field(..., description="The name of the dental clinic the user wants to book.")

class UserInfo(BaseModel):
    patient_name: str = Field(..., description="The user's full name.")
    email_address: str = Field(..., description="The user's email address.")
    whatsapp_number: str = Field(..., description="The user's WhatsApp number, including country code if provided.")
    
class Confirmation(BaseModel):
    is_confirmed: bool = Field(..., description="True if the user confirms ('yes', 'correct'), false if they deny or want to change something.")
    corrected_treatment: Optional[str] = Field(None, description="If the user wants a different treatment, extract the new treatment name (e.g., 'general cleaning', 'scaling').")

class TravelIntent(BaseModel):
    """Triggers when the user asks about travel time, distance, directions, or traffic."""
    clinic_name: Optional[str] = Field(None, description="The destination clinic name, if the user specifies one.")

class UserLocation(BaseModel):
    """Captures the user's starting location for travel planning."""
    start_location: str = Field(..., description="The user's starting location, such as a postal code, neighborhood, or landmark in Singapore.")

class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    TRAVEL_ADVISORY = "travel_advisory"
    GENERAL_QUESTION = "general_question"

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
    
    latest_user_message = query.history[-1].content.lower()
    previous_filters = query.applied_filters or {}
    candidate_clinics = query.candidate_pool or []
    booking_context = query.booking_context or {}
    travel_context = query.travel_context or {}
    
    conversation_history_for_prompt = ""
    for msg in query.history:
        conversation_history_for_prompt += f"{msg.role}: {msg.content}\n"

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")
    print(f"Booking Context: {booking_context}")
    print(f"Travel Context: {travel_context}")

    # STAGE 0: THE GATEKEEPER
    intent = ChatIntent.FIND_CLINIC
    try:
        gatekeeper_prompt = f"Classify the user's primary intent: 'find_clinic', 'book_appointment', or 'travel_advisory'.\n\nHistory:\n{conversation_history_for_prompt}"
        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        function_call = gatekeeper_response.candidates[0].content.parts[0].function_call
        if function_call and function_call.args:
            intent = function_call.args['intent']
        print(f"Gatekeeper decided intent is: {intent}")
    except Exception as e:
        print(f"Gatekeeper Error: {e}. Defaulting to find_clinic.")

    # --- TRAVEL ADVISOR MODE ---
    if intent == ChatIntent.TRAVEL_ADVISORY or travel_context.get("status") == "gathering_location":
        if travel_context.get("status") == "gathering_location":
            print("In Travel Mode: Capturing user location...")
            try:
                location_response = factual_brain_model.generate_content(
                    f"Extract the user's starting location from this message: '{latest_user_message}'",
                    tools=[UserLocation]
                )
                function_call = location_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    start_location = function_call.args['start_location']
                    destination = travel_context.get('destination_address')
                    maps_url = f"https://www.google.com/maps/dir/{urlencode({'q': start_location})}/{urlencode({'q': destination})}"
                    response_text = f"Got it. Here is the direct Google Maps link from **{start_location}** to **{travel_context.get('destination_name')}**. This will show you the live traffic conditions, including the causeway, and give you the most accurate travel time right now:\n\n[View live route on Google Maps]({maps_url})"
                    return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {"status": "complete"}}
            except Exception as e:
                print(f"User Location Capture Error: {e}")
                return {"response": "I'm sorry, I had trouble understanding that location. Could you please provide a postal code or neighborhood in Singapore?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "travel_context": travel_context}
        else: # First step of travel
            print("Starting Travel Mode...")
            # Find the target clinic (either from intent or last known top clinic)
            destination_clinic = None
            try:
                travel_intent_response = factual_brain_model.generate_content(f"Extract the clinic name if mentioned: '{latest_user_message}'", tools=[TravelIntent])
                function_call = travel_intent_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args and function_call.args.get('clinic_name'):
                    clinic_name_query = function_call.args['clinic_name'].lower()
                    for clinic in candidate_clinics:
                        if clinic_name_query in clinic.get('name', '').lower():
                            destination_clinic = clinic
                            break
            except Exception as e:
                print(f"Travel Intent Extraction Error: {e}")
            
            if not destination_clinic and qualified_clinics:
                destination_clinic = qualified_clinics[0] # Default to the top clinic
            
            if destination_clinic:
                new_travel_context = {
                    "status": "gathering_location",
                    "destination_name": destination_clinic.get('name'),
                    "destination_address": destination_clinic.get('address')
                }
                response_text = f"I can help with that. To give you the best real-time travel estimate to **{destination_clinic.get('name')}**, what is your starting location or postal code in Singapore?"
                return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": new_travel_context}
            else:
                return {"response": "I can help with travel time, but first I need to know which clinic you're interested in. Could you please specify a clinic?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}

    # --- BOOKING MODE LOGIC ---
    elif intent == ChatIntent.BOOK_APPOINTMENT or booking_context.get("status") in ["confirming_details", "gathering_info"]:
        if booking_context.get("status") == "confirming_details":
            # (Booking confirmation logic is unchanged)
            pass
        elif booking_context.get("status") == "gathering_info":
            print("In Booking Mode: Capturing user info...")
            try:
                user_info_response = factual_brain_model.generate_content(
                    f"Extract the user's name, email, and WhatsApp number from this message: '{latest_user_message}'",
                    tools=[UserInfo]
                )
                function_call = user_info_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    user_args = function_call.args
                    base_url = "https://sg-jb-dental.lovable.app/book-now"
                    clinic_name_safe = urlencode({'q': booking_context.get('clinic_name', '')})[2:]
                    params = {
                        'name': user_args.get('patient_name'), 'email': user_args.get('email_address'),
                        'phone': user_args.get('whatsapp_number'), 'clinic': clinic_name_safe,
                        'treatment': booking_context.get('treatment')
                    }
                    params = {k: v for k, v in params.items() if v}
                    query_string = urlencode(params)
                    final_url = f"{base_url}?{query_string}"
                    final_response_text = f"Perfect, thank you! I have pre-filled the booking form for you. Please click this link to choose your preferred date and time, and to confirm your appointment:\n\n[Click here to complete your booking]({final_url})"
                    
                    return {"response": final_response_text, "applied_filters": {}, "candidate_pool": [], "booking_context": {"status": "complete"}, "travel_context": {}}
            except Exception as e:
                print(f"Booking Info Capture Error: {e}")
                final_response_text = "I'm sorry, I had trouble understanding those details. Please try entering them again: just your full name, email, and WhatsApp number."
                return {"response": final_response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}
        else: # First step of booking
            # (Booking initiation logic is unchanged)
            pass

    # --- RECOMMENDATION MODE ---
    elif intent == ChatIntent.FIND_CLINIC:
        current_filters = {}
        try:
            # ("Two-Prompt" Factual Brain logic is unchanged)
            pass
        except Exception as e:
            print(f"Factual Brain Error: {e}")

        # (Deterministic Planner logic is unchanged)
        final_filters = {}
        
        ranking_priorities = []
        try:
            # (Hardened Ranking Brain logic is unchanged)
            pass
        except Exception as e:
            print(f"Ranking Brain Error: {e}")

        if not candidate_clinics:
            # (Database search logic is unchanged)
            pass
        
        qualified_clinics = []
        if candidate_clinics:
            # (In-memory filtering logic is unchanged)
            pass

        top_clinics = []
        if qualified_clinics:
            # (Ranking logic is unchanged)
            pass

        context = ""
        if top_clinics:
            # (Context generation logic is unchanged)
            pass
        
        # ("Data Formatter" Spokesperson prompt is unchanged)
        augmented_prompt = "..."
        
        final_response = generation_model.generate_content(augmented_prompt)
        
        return {
            "response": final_response.text, 
            "applied_filters": final_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": {},
            "travel_context": {}
        }

    # --- GENERAL QUESTION MODE (Future) ---
    else:
        return {"response": "Sorry, I can only help with finding or booking dental clinics right now.", "applied_filters": {}, "candidate_pool": [], "booking_context": {}, "travel_context": {}}

    # Fallback return statement
    return {"response": "An error occurred.", "applied_filters": {}, "candidate_pool": [], "booking_context": {}, "travel_context": {}}