import json
import string
import google.generativeai as genai
import numpy as np
from numpy.linalg import norm
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List

# --- Pydantic Models required for this flow ---
class ServiceEnum(str, Enum):
    scaling = 'scaling'; braces = 'braces'; tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; teeth_whitening = 'teeth_whitening'; veneers = 'veneers'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_ veneers'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; enamel_shaping = 'enamel_shaping'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'; general_dentistry = 'general_dentistry'
    
class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

# --- The main handler function for this flow ---
def handle_find_clinic(latest_user_message, conversation_history, previous_filters, candidate_clinics, factual_brain_model, ranking_brain_model, embedding_model, generation_model, supabase, RESET_KEYWORDS):
    current_filters = {}
    try:
        prompt_text = f"""
        You are an expert entity extractor. Your only job is to analyze the user's most recent query and call the `UserIntent` tool.
        If the user uses a pronoun like "them" or "that", look at the previous assistant message to understand what it refers to.
        If you find a specific dental service and/or a location, extract them.
        If no specific dental service or location is mentioned, call the tool with null values for both fields.
        You MUST always call the `UserIntent` tool.

        Conversation History:
        {conversation_history}

        Extract entities from the LATEST user query: "{latest_user_message}"
        """
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

    if 'township' in current_filters:
        current_filters['township'] = current_filters['township'].rstrip(string.punctuation).lower()
        print(f"Sanitized township to: '{current_filters['township']}'")

    final_filters = {}
    user_wants_to_reset = any(keyword in latest_user_message for keyword in RESET_KEYWORDS)

    if user_wants_to_reset:
        final_filters = current_filters; candidate_clinics = []
    elif ('services' in current_filters and 'township' not in current_filters) or ('township' in current_filters and 'services' not in current_filters):
        final_filters = current_filters; candidate_clinics = []
    else:
        final_filters = previous_filters.copy(); final_filters.update(current_filters)
    
    print(f"Final Filters to be applied: {final_filters}")

    db_query = supabase.table('clinics_data').select('*')

    if 'services' in final_filters:
        for service in final_filters['services']:
            sanitized_service = service.replace(' ', '_')
            db_query = db_query.eq(sanitized_service, True)
    
    township_filter = final_filters.get('township')
    if township_filter in ['jb', 'johor bahru']:
        print("Applying Metro JB filter...")
        db_query = db_query.eq('is_metro_jb', True)
    elif township_filter:
        print(f"Applying specific township filter: {township_filter}")
        db_query = db_query.eq('township', township_filter)

    try:
        response = db_query.execute()
        candidate_clinics = response.data if response.data else []
        print(f"Found {len(candidate_clinics)} candidates after initial database filtering.")
    except Exception as e:
        print(f"Database query error: {e}")
        candidate_clinics = []
    
    qualified_clinics = []
    if candidate_clinics:
        quality_gated_clinics = [c for c in candidate_clinics if c.get('rating', 0) >= 4.5 and c.get('reviews', 0) >= 30]
        print(f"Found {len(quality_gated_clinics)} candidates after Quality Gate.")
        qualified_clinics = quality_gated_clinics

    top_clinics = []
    if qualified_clinics:
        top_clinics = qualified_clinics[:3]

    if not top_clinics:
        return {"response": "I'm sorry, I couldn't find any clinics that match your specific criteria. Would you like to try a different search?", "applied_filters": final_filters, "candidate_pool": [], "booking_context": {}}

    context = json.dumps([{"position": i + 1, **{k: clinic.get(k) for k in ['name', 'address', 'rating', 'reviews', 'website_url', 'operating_hours']}} for i, clinic in enumerate(top_clinics)], indent=2)
    
    augmented_prompt = f'You are a Data Formatter... **Data:**\n```json\n{context}\n```\n--- Your Formatting Task: ...'
    
    response_text = ""
    try:
        ai_response = generation_model.generate_content(augmented_prompt)
        response_text = ai_response.text
        
        if not response_text or not response_text.strip():
             raise ValueError("AI returned an empty response.")

    except Exception as e:
        print(f"CRITICAL FALLBACK: Data Formatter AI failed. Reason: {e}. Providing a manual fallback response.")
        
        fallback_list = []
        for clinic in top_clinics:
            fallback_list.append(f"- **{clinic.get('name')}** (Rating: {clinic.get('rating')}, Reviews: {clinic.get('reviews')})")
        
        response_text = "I found a few highly-rated clinics for you:\n" + "\n".join(fallback_list) + "\n\nWould you like to book an appointment at one of these locations?"

    return {
        "response": response_text, 
        "applied_filters": final_filters,
        "candidate_pool": candidate_clinics,
        "booking_context": {}
    }