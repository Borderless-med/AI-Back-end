import json
import string
import google.generativeai as genai
import numpy as np
from numpy.linalg import norm
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List

class ServiceEnum(str, Enum):
    scaling = 'scaling'; braces = 'braces'; tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; teeth_whitening = 'teeth_whitening'; veneers = 'veneers'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; enamel_shaping = 'enamel_shaping'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'; general_dentistry = 'general_dentistry'
    
class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

def handle_find_clinic(latest_user_message, conversation_history, previous_filters, candidate_clinics, factual_brain_model, ranking_brain_model, embedding_model, generation_model, supabase, RESET_KEYWORDS):
    current_filters = {}
    try:
        print("Factual Brain: Attempting Tool Call...")
        prompt_text = f"""
                You are an expert entity extractor. Analyze the user's most recent query in the context of the conversation history to extract a specific dental service and/or a location.
                If the user uses a pronoun like "them" or "that", look at the previous assistant message to understand what it refers to.

                Conversation History:
                {conversation_history}

                Extract entities from the LATEST user query only.
                """
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
            safety_net_prompt = f'Analyze the user\'s query and extract information into a JSON object. User Query: "{latest_user_message}"\n 1. **service**: Does the query mention a dental service from this exact list: [{service_list_str}]? If yes, return the exact service name. If no, return null.\n 2. **township**: Does the query mention a location or township? If yes, return the location name. If no, return null.\n Your response MUST be a single, valid JSON object and nothing else.'
            safety_net_response = factual_brain_model.generate_content(safety_net_prompt)
            json_text = safety_net_response.text.strip().replace("```json", "").replace("```", "")
            extracted_data = json.loads(json_text)
            if extracted_data.get('service'): current_filters['services'] = [extracted_data.get('service')]
            if extracted_data.get('township'): current_filters['township'] = extracted_data.get('township')
        print(f"Factual Brain extracted: {current_filters}")
    except Exception as e:
        print(f"Factual Brain Error: {e}")

    if 'township' in current_filters:
        current_filters['township'] = current_filters['township'].rstrip(string.punctuation)
        print(f"Sanitized township to: '{current_filters['township']}'")

    final_filters = {}
    user_wants_to_reset = any(keyword in latest_user_message for keyword in RESET_KEYWORDS)

    if user_wants_to_reset:
        final_filters = current_filters; candidate_clinics = []
    elif 'services' in current_filters and 'township' not in current_filters:
        final_filters = current_filters; candidate_clinics = []
    elif 'township' in current_filters and 'services' not in current_filters:
        final_filters = current_filters; candidate_clinics = []
    else:
        final_filters = previous_filters.copy(); final_filters.update(current_filters)
    
    print(f"Final Filters to be applied: {final_filters}")

    ranking_priorities = []
    try:
        ranking_prompt = f'Analyze the user\'s latest query to determine ranking priorities. Respond with a JSON list: [\"sentiment_dentist_skill\", \"sentiment_cost_value\", \"sentiment_convenience\"]. User Query: "{latest_user_message}"'
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
                # --- THIS IS THE CORRECTED FILTERING LOGIC ---
                if 'township' in final_filters:
                    township_filter = final_filters['township'].lower()
                    clinic_address = clinic.get('address', '').lower()
                    aliases = {'jb': ['johor bahru'], 'permas': ['permas jaya']}
                    allowed_terms = [township_filter]
                    if township_filter in aliases:
                        allowed_terms.extend(aliases[township_filter])
                    if not any(term in clinic_address for term in allowed_terms):
                        match = False
                
                if match and final_filters.get('services'):
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
            ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in list(dict.fromkeys(ranking_priorities + ['rating', 'reviews']))), reverse=True)
        else:
            max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
            for clinic in qualified_clinics:
                norm_rating = (clinic.get('rating', 0) - 1) / 4.0
                norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
                clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
            ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
        top_clinics = ranked_clinics[:3]

    context = ""
    if top_clinics:
        context = json.dumps([{"position": i + 1, **{k: clinic.get(k) for k in ['name', 'address', 'rating', 'reviews', 'website_url', 'operating_hours']}} for i, clinic in enumerate(top_clinics)], indent=2)
    
    augmented_prompt = f'You are a Data Formatter... **Data:**\n```json\n{context}\n```\n--- Your Formatting Task: ...' # Simplified for brevity
    final_response = generation_model.generate_content(augmented_prompt)
    
    return {
        "response": final_response.text, 
        "applied_filters": final_filters,
        "candidate_pool": candidate_clinics,
        "booking_context": {}
    }