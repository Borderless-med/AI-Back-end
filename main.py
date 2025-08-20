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
    clinic_name: Optional[str] = Field(None, description="The destination clinic name, if the user specifies one.")

class UserLocation(BaseModel):
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
        else:
            print("Starting Travel Mode...")
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
            
            if not destination_clinic and candidate_clinics:
                if len(candidate_clinics) > 0:
                    destination_clinic = candidate_clinics[0]

            if destination_clinic:
                new_travel_context = {
                    "status": "gathering_location", "destination_name": destination_clinic.get('name'),
                    "destination_address": destination_clinic.get('address')
                }
                response_text = f"I can help with that. To give you the best real-time travel estimate to **{destination_clinic.get('name')}**, what is your starting location or postal code in Singapore?"
                return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": new_travel_context}
            else:
                return {"response": "I can help with travel time, but first I need to know which clinic you're interested in. Could you please specify a clinic?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}

    # --- BOOKING MODE LOGIC ---
    elif intent == ChatIntent.BOOK_APPOINTMENT or booking_context.get("status") in ["confirming_details", "gathering_info"]:
        if booking_context.get("status") == "confirming_details":
            print("In Booking Mode: Processing user confirmation...")
            try:
                confirmation_response = factual_brain_model.generate_content(f"Analyze the user's reply to the confirmation question. Reply: '{latest_user_message}'", tools=[Confirmation])
                function_call = confirmation_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    confirm_args = function_call.args
                    if confirm_args.get("is_confirmed"):
                        booking_context["status"] = "gathering_info"
                        response_text = "Perfect. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
                        return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}
                    else:
                        if confirm_args.get("corrected_treatment"):
                            booking_context["treatment"] = confirm_args.get("corrected_treatment")
                            response_text = f"Got it, thank you for clarifying. So that's an appointment for **{booking_context['treatment']}** at **{booking_context['clinic_name']}**. Is that correct?"
                            return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}
            except Exception as e:
                print(f"Booking Confirmation Error: {e}")
                booking_context["status"] = "gathering_info"
                response_text = "My apologies, I had a little trouble there. Let's proceed. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
                return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}
        elif booking_context.get("status") == "gathering_info":
            print("In Booking Mode: Capturing user info...")
            try:
                user_info_response = factual_brain_model.generate_content(f"Extract the user's name, email, and WhatsApp number from this message: '{latest_user_message}'", tools=[UserInfo])
                function_call = user_info_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    user_args = function_call.args
                    base_url = "https://sg-jb-dental.lovable.app/book-now"
                    clinic_name_safe = urlencode({'q': booking_context.get('clinic_name', '')})[2:]
                    params = {'name': user_args.get('patient_name'), 'email': user_args.get('email_address'), 'phone': user_args.get('whatsapp_number'), 'clinic': clinic_name_safe, 'treatment': booking_context.get('treatment')}
                    params = {k: v for k, v in params.items() if v}
                    query_string = urlencode(params)
                    final_url = f"{base_url}?{query_string}"
                    final_response_text = f"Perfect, thank you! I have pre-filled the booking form for you. Please click this link to choose your preferred date and time, and to confirm your appointment:\n\n[Click here to complete your booking]({final_url})"
                    return {"response": final_response_text, "applied_filters": {}, "candidate_pool": [], "booking_context": {"status": "complete"}, "travel_context": {}}
            except Exception as e:
                print(f"Booking Info Capture Error: {e}")
                final_response_text = "I'm sorry, I had trouble understanding those details. Please try entering them again: just your full name, email, and WhatsApp number."
                return {"response": final_response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context, "travel_context": {}}
        else:
            print("Starting Booking Mode: Confirming details...")
            try:
                booking_intent_response = factual_brain_model.generate_content(f"From the user's message, extract the name of the clinic they want to book. Message: '{latest_user_message}'", tools=[BookingIntent])
                function_call = booking_intent_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    booking_args = function_call.args
                    clinic_name = booking_args.get('clinic_name')
                    treatment = (previous_filters.get('services') or ["a consultation"])[0]
                    new_booking_context = {"status": "confirming_details", "clinic_name": clinic_name, "treatment": treatment}
                    response_text = f"Great! I can help you get started with booking. Just to confirm, are you looking to book an appointment for **{treatment}** at **{clinic_name}**?"
                    return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": new_booking_context, "travel_context": {}}
            except Exception as e:
                print(f"Booking Intent Extraction Error: {e}")
                return {"response": "I can help with that. Which clinic would you like to book?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}, "travel_context": {}}

    # --- RECOMMENDATION MODE ---
    elif intent == ChatIntent.FIND_CLINIC:
        current_filters = {}
        try:
            print("Factual Brain: Attempting Tool Call...")
            prompt_text = f"Extract entities from this query: '{latest_user_message}'"
            factual_response = factual_brain_model.generate_content(prompt_text, tools=[UserIntent])
            if factual_response.candidates and factual_response.candidates[0].content.parts:
                function_call = factual_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    args = function_call.args
                    if args.get('service'): current_filters['services'] = [args.get('service')]
                    if args.get('township'): current_filters['township'] = args.get('township')
            if not current_filters:
                print("Factual Brain: Tool Call failed. Attempting Safety Net Prompt...")
                service_list_str = ", ".join([f"'{e.value}'" for e in ServiceEnum])
                safety_net_prompt = f"""
                Analyze the user's query and extract information into a JSON object.
                User Query: "{latest_user_message}"
                1.  **service**: Does the query mention a dental service from this exact list: [{service_list_str}]? If yes, return the exact service name. If no, return null.
                2.  **township**: Does the query mention a location or township? If yes, return the location name. If no, return null.
                Your response MUST be a single, valid JSON object and nothing else.
                Example: {{"service": "dental_implant", "township": "johor bahru"}}
                """
                safety_net_response = factual_brain_model.generate_content(safety_net_prompt)
                json_text = safety_net_response.text.strip().replace("```json", "").replace("```", "")
                extracted_data = json.loads(json_text)
                if extracted_data.get('service'): current_filters['services'] = [extracted_data.get('service')]
                if extracted_data.get('township'): current_filters['township'] = extracted_data.get('township')
            print(f"Factual Brain extracted: {current_filters}")
        except Exception as e:
            print(f"Factual Brain Error: {e}")

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
            ranking_prompt = f"""
            Analyze the user's latest query to determine their ranking priorities. Your response MUST be a valid JSON list of strings.
            The list can contain 'sentiment_dentist_skill', 'sentiment_cost_value', 'sentiment_convenience'.
            - If query mentions 'convenience', 'location', 'near', include "sentiment_convenience".
            - If query mentions 'quality', 'skill', 'best', 'top-rated', or a complex service, include "sentiment_dentist_skill".
            - If query mentions 'cost', 'value', 'affordable', 'cheap', include "sentiment_cost_value".
            - If multiple are mentioned, return them in order of importance. If ambiguous, return an empty list [].
            User Query: "{latest_user_message}"
            Respond with ONLY the JSON list.
            """
            ranking_response = ranking_brain_model.generate_content(ranking_prompt)
            print(f"Ranking Brain raw response: {ranking_response.text}")
            json_text = ranking_response.text.strip().replace("```json", "").replace("```", "")
            ranking_priorities = json.loads(json_text)
            print(f"Ranking Brain determined priorities: {ranking_priorities}")
        except Exception as e:
            print(f"Ranking Brain Error: {e}")

        if not candidate_clinics:
            print("Candidate pool is empty. Performing initial database search.")
            try:
                search_text = latest_user_message if not final_filters else json.dumps(final_filters)
                query_embedding_response = genai.embed_content(model=embedding_model, content=search_text, task_type="RETRIEVAL_QUERY")
                query_embedding_list = query_embedding_response['embedding']
                query_embedding_text = "[" + ",".join(map(str, query_embedding_list)) + "]"
                db_response = supabase.rpc('match_clinics_simple', {'query_embedding_text': query_embedding_text, 'match_count': 75}).execute()
                candidate_clinics = db_response.data if db_response.data else []
                print(f"Found {len(candidate_clinics)} initial candidates from semantic search.")
            except Exception as e:
                print(f"Semantic search DB function error: {e}")
        else:
            print(f"Using existing candidate pool of {len(candidate_clinics)} clinics.")

        qualified_clinics = []
        if candidate_clinics:
            quality_gated_clinics = [c for c in candidate_clinics if c.get('rating', 0) >= 4.5 and c.get('reviews', 0) >= 30]
            print(f"Found {len(quality_gated_clinics)} candidates after Quality Gate.")
            if final_filters:
                factually_filtered_clinics = []
                for clinic in quality_gated_clinics:
                    match = True
                    if final_filters.get('township') and final_filters.get('township').lower() not in clinic.get('address', '').lower(): match = False
                    if final_filters.get('services'):
                        for service in final_filters.get('services'):
                            if not clinic.get(service, False): match = False; break
                    if match: factually_filtered_clinics.append(clinic)
                qualified_clinics = factually_filtered_clinics
            else:
                qualified_clinics = quality_gated_clinics
            print(f"Found {len(qualified_clinics)} candidates after applying Factual Filters.")

        top_clinics = []
        if qualified_clinics:
            if ranking_priorities:
                print(f"Applying SENTIMENT-FIRST ranking with priorities: {ranking_priorities}")
                ranking_keys = ranking_priorities + ['rating', 'reviews']
                unique_keys = list(dict.fromkeys(ranking_keys))
                ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in unique_keys), reverse=True)
            else:
                print("Applying OBJECTIVE-FIRST weighted score.")
                max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
                for clinic in qualified_clinics:
                    norm_rating = (clinic.get('rating', 0) - 1) / 4.0
                    norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
                    clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
                ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
            top_clinics = ranked_clinics[:3]
            print(f"Ranking complete. Top clinic: {top_clinics[0]['name'] if top_clinics else 'N/A'}")

        context = ""
        if top_clinics:
            clinic_data_for_prompt = []
            for i, clinic in enumerate(top_clinics):
                clinic_info = {"position": i + 1, "name": clinic.get('name'), "address": clinic.get('address'), "rating": clinic.get('rating'), "reviews": clinic.get('reviews'), "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours')}
                clinic_data_for_prompt.append(clinic_info)
            context = json.dumps(clinic_data_for_prompt, indent=2)
        
        augmented_prompt = f"""
        You are a Data Formatter. Your only job is to present the user with a list of dental clinics based on the pre-ranked JSON data provided below. You MUST NOT change the order of the clinics.
        **Data (Pre-ranked list of clinics):**
        ```json
        {context}
        ```
        ---
        **Your Formatting Task:**
        1.  **Analyze User's Query:** Review the user's original query: "{latest_user_message}".
        2.  **Present Clinics in Order:** Display the clinics from the JSON data in the exact order provided. Use "Top Recommendation" for position 1 and "Alternative Option(s)" for others. Format details as bullet points.
        3.  **Add Concluding Note:** After the list, add a "Please note:" section. If the user's query contained subjective words (like "best" or "affordable"), your note must be honest about this limitation. Example: "Please note: While I've ranked these clinics based on their high ratings, 'best' is subjective and I recommend checking recent reviews."
        ---
        """
        final_response = generation_model.generate_content(augmented_prompt)
        
        return {
            "response": final_response.text, 
            "applied_filters": final_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": {}
        }

    else:
        return {"response": "An error occurred in routing.", "applied_filters": {}, "candidate_pool": [], "booking_context": {}}