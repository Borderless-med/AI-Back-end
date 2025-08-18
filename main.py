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

    # --- STAGE 0: THE GATEKEEPER ---
    intent = ChatIntent.FIND_CLINIC
    try:
        gatekeeper_prompt = f"Classify the user's primary intent based on their latest message and the conversation history. Choose 'book_appointment' if they are clearly trying to schedule a visit. Otherwise, choose 'find_clinic'.\n\nHistory:\n{conversation_history_for_prompt}"
        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        function_call = gatekeeper_response.candidates[0].content.parts[0].function_call
        if function_call and function_call.args:
            intent = function_call.args['intent']
        print(f"Gatekeeper decided intent is: {intent}")
    except Exception as e:
        print(f"Gatekeeper Error: {e}. Defaulting to find_clinic.")

    # --- BOOKING MODE LOGIC ---
    if intent == ChatIntent.BOOK_APPOINTMENT or booking_context.get("status") == "gathering_info":
        if booking_context.get("status") == "gathering_info":
            print("In Booking Mode: Capturing user info...")
            try:
                user_info_response = factual_brain_model.generate_content(
                    f"Extract the user's name, email, and WhatsApp number from this message: '{latest_user_message}'",
                    tools=[UserInfo]
                )
                function_call = user_info_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    user_args = function_call.args
                    base_url = "https://www.sg-jb-dental.com/book-now"
                    
                    # THE FINAL FIX: URL-encode the clinic name to handle special characters
                    clinic_name_safe = urlencode({'q': booking_context.get('clinic_name', '')})[2:]
                    
                    params = {
                        'name': user_args.get('patient_name'),
                        'email': user_args.get('email_address'),
                        'phone': user_args.get('whatsapp_number'),
                        'clinic': clinic_name_safe, # Use the new, safe version
                        'treatment': booking_context.get('treatment')
                    }
                    params = {k: v for k, v in params.items() if v is not None}
                    query_string = urlencode(params)
                    final_url = f"{base_url}?{query_string}"
                    final_response_text = f"Perfect, thank you! I have pre-filled the booking form for you. Please click this link to choose your preferred date and time, and to confirm your appointment:\n\n[Click here to complete your booking]({final_url})"
                    
                    return {
                        "response": final_response_text,
                        "applied_filters": {}, "candidate_pool": [],
                        "booking_context": {"status": "complete"}
                    }
            except Exception as e:
                print(f"Booking Info Capture Error: {e}")
                final_response_text = "I'm sorry, I had trouble understanding those details. Could you please try entering them again? Just your name, email, and WhatsApp number."
                return {
                    "response": final_response_text, "applied_filters": previous_filters,
                    "candidate_pool": candidate_clinics, "booking_context": booking_context
                }
        else: # This is the first step of booking
            print("Starting Booking Mode...")
            try:
                booking_intent_response = factual_brain_model.generate_content(
                    f"From the user's message, extract the name of the clinic they want to book. Message: '{latest_user_message}'",
                    tools=[BookingIntent]
                )
                function_call = booking_intent_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    booking_args = function_call.args
                    clinic_name = booking_args.get('clinic_name')
                    treatment = (previous_filters.get('services') or [None])[0]
                    new_booking_context = {"status": "gathering_info", "clinic_name": clinic_name, "treatment": treatment}
                    response_text = f"Great! I can help you get started with booking an appointment for **{treatment or 'a consultation'}** at **{clinic_name}**. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
                    
                    return {
                        "response": response_text, "applied_filters": previous_filters,
                        "candidate_pool": candidate_clinics, "booking_context": new_booking_context
                    }
            except Exception as e:
                print(f"Booking Intent Extraction Error: {e}")
                return {"response": "I can help with that. Which clinic would you like to book?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}}

    # --- RECOMMENDATION MODE ---
    elif intent == ChatIntent.FIND_CLINIC:
        current_filters = {}
        try:
            prompt_text = f"Extract entities from this query: '{latest_user_message}'"
            factual_response = factual_brain_model.generate_content(prompt_text, tools=[UserIntent])
            if factual_response.candidates and factual_response.candidates[0].content.parts:
                function_call = factual_response.candidates[0].content.parts[0].function_call
                if function_call and function_call.args:
                    args = function_call.args
                    if args.get('service'): current_filters['services'] = [args.get('service')]
                    if args.get('township'): current_filters['township'] = args.get('township')
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
            Analyze the user's intent from the history and latest query. Your output MUST be a valid JSON list of strings and nothing else.
            The list can contain 'sentiment_dentist_skill', 'sentiment_cost_value', 'sentiment_convenience'.
            - For complex services ('implant', 'braces', 'root canal'), prioritize 'sentiment_dentist_skill'.
            - For cosmetic services ('whitening', 'veneers'), prioritize 'sentiment_cost_value'.
            - For location queries ('near', 'in'), prioritize 'sentiment_convenience'.
            - If the intent is ambiguous or general, return an empty list [].
            History: {conversation_history_for_prompt}
            Latest Query: "{latest_user_message}"
            Respond with ONLY the JSON list. Do not add any other text or markdown.
            """
            ranking_response = ranking_brain_model.generate_content(ranking_prompt)
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
            for clinic in top_clinics:
                clinic_info = { "name": clinic.get('name'), "address": clinic.get('address'), "rating": clinic.get('rating'), "reviews": clinic.get('reviews'), "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),}
                clinic_data_for_prompt.append(clinic_info)
            context = json.dumps(clinic_data_for_prompt, indent=2)
        
        augmented_prompt = f"""
        You are a helpful and expert AI dental concierge. Your goal is to provide a clear, data-driven answer to the user's question.
        **Conversation History (for context):**
        {conversation_history_for_prompt}
        **User's Latest Question:**
        "{latest_user_message}"
        **Data You Must Use To Answer:**
        ```json
        {context}
        ```
        ---
        **Your Task:**
        1.  **Answer the User's Question:** Directly address their latest query using the data provided.
        2.  **Present the Data Clearly:** Format your response with clinic names, ratings, and addresses as bullet points.
        3.  **Be Honest About Limitations:** If the user asks for something you can't objectively prove from the data (like "best", "affordable", or "cheapest"), you MUST include a brief, friendly note explaining this. For example: "Please note: while I can find highly-rated clinics, 'best' is subjective and I recommend checking recent reviews." or "I've ranked these based on positive sentiment about value, but I don't have access to real-time pricing to guarantee affordability."
        4.  **Handle "No Results":** If the DATABASE SEARCH RESULTS are empty (`{{}}`), you MUST inform the user clearly and politely that you could not find any clinics that matched their specific criteria.
        ---
        """
        
        final_response = generation_model.generate_content(augmented_prompt)
        return {
            "response": final_response.text, 
            "applied_filters": final_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": {}
        }

    # --- GENERAL QUESTION MODE (Future) ---
    else:
        return {"response": "Sorry, I can only help with finding or booking dental clinics right now.", "applied_filters": {}, "candidate_pool": [], "booking_context": {}}

    return {"response": "An error occurred.", "applied_filters": {}, "candidate_pool": [], "booking_context": {}}