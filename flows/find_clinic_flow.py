import json
import string
import google.generativeai as genai
import numpy as np
from numpy.linalg import norm
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Tuple, Dict

# --- Pydantic Models required for this flow ---
class ServiceEnum(str, Enum):
    scaling = 'scaling'; braces = 'braces'; tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; teeth_whitening = 'teeth_whitening'; veneers = 'veneers'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; enamel_shaping = 'enamel_shaping'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'; general_dentistry = 'general_dentistry'
    
class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

# --- The main handler function for this flow ---
def handle_find_clinic(latest_user_message, conversation_history, previous_filters, candidate_clinics, factual_brain_model, ranking_brain_model, embedding_model, generation_model, supabase, RESET_KEYWORDS, session_state: dict = None):
    """
    Enhanced find clinic flow with early location preference gate.
    - session_state may contain:
        - location_preference: 'jb' | 'sg' | 'all'
        - awaiting_location: bool
    Returns a dict that may include 'state_update' to be merged into session state by the caller.
    """
    session_state = session_state or {}
    state_update = {}
    location_preference = session_state.get('location_preference')
    awaiting_location = session_state.get('awaiting_location', False)
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

    # Deterministic fallback for service extraction when LLM misses or is inconsistent
    def heuristic_service_from_text(text: str) -> Optional[str]:
        t = (text or '').lower()
        # Prefer specific procedures before general cleaning/scaling
        patterns = [
            (['root canal', 'endodontic'], 'root_canal'),
            (['implant', 'dental implant'], 'dental_implant'),
            (['crown', 'cap'], 'dental_crown'),
            (['filling', 'tooth filling'], 'tooth_filling'),
            (['whitening', 'bleaching'], 'teeth_whitening'),
            (['braces', 'orthodontic'], 'braces'),
            (['wisdom tooth', 'wisdom extraction'], 'wisdom_tooth'),
            (['gum', 'periodontal'], 'gum_treatment'),
            (['veneers'], 'veneers'),
            (['cleaning', 'polish', 'scale', 'scaling'], 'scaling'),
        ]
        for keys, svc in patterns:
            if any(k in t for k in keys):
                return svc
        return None

    # Minimal township heuristics (helps when LLM misses simple "in/near X" phrases)
    def heuristic_township_from_text(text: str) -> Optional[str]:
        t = (text or '').lower()
        # very simple patterns; we only use as a fallback when LLM returns nothing
        for kw in [' near ', ' in ']:
            if kw in t:
                # take up to 3 tokens after the keyword as a loose area name guess
                tail = t.split(kw, 1)[1].strip()
                tokens = [tok.strip(string.punctuation) for tok in tail.split()]
                guess = " ".join(tokens[:3]).strip()
                # avoid capturing country words or empty
                if guess and guess not in { 'singapore', 'sg', 'johor', 'jb', 'johor bahru' }:
                    return guess
        return None

    # If no service extracted, or extracted one conflicts with an obvious heuristic match, prefer heuristic
    heuristic_svc = heuristic_service_from_text(latest_user_message)
    if heuristic_svc:
        if 'services' not in current_filters or (current_filters['services'] and current_filters['services'][0] != heuristic_svc):
            current_filters['services'] = [heuristic_svc]
            print(f"[Heuristic] Service set to '{heuristic_svc}' from user text fallback")

    if 'township' in current_filters and current_filters['township']:
        current_filters['township'] = current_filters['township'].rstrip(string.punctuation).strip()
        print(f"Sanitized township to: '{current_filters['township'].lower()}'")
    elif not current_filters.get('township'):
        ht = heuristic_township_from_text(latest_user_message)
        if ht:
            current_filters['township'] = ht.rstrip(string.punctuation).strip()
            print(f"[Heuristic] Township set to '{current_filters['township']}' from user text fallback")

    final_filters = {}
    user_wants_to_reset = any(keyword in latest_user_message for keyword in RESET_KEYWORDS)

    if user_wants_to_reset:
        final_filters = current_filters; candidate_clinics = []
        # Clear any persisted location so next search prompts again
        state_update['location_preference'] = None
        state_update['awaiting_location'] = False
    elif ('services' in current_filters and 'township' not in current_filters) or ('township' in current_filters and 'services' not in current_filters):
        final_filters = current_filters; candidate_clinics = []
    else:
        final_filters = previous_filters.copy(); final_filters.update(current_filters)
    
    # defer logging of final filters until after location routing normalization below

    # --- LOCATION PREFERENCE GATE ---
    # 1) Try to infer from current message if awaiting or missing
    def infer_location_from_text(text: str) -> Optional[str]:
        t = (text or '').lower()
        if any(k in t for k in ['both', 'all']):
            return 'all'
        if any(k in t for k in ['singapore', 'sg']):
            return 'sg'
        if any(k in t for k in ['johor bahru', 'johor', 'jb']):
            return 'jb'
        return None

    inferred = infer_location_from_text(latest_user_message)
    if inferred and (awaiting_location or not location_preference):
        location_preference = inferred
        state_update['location_preference'] = inferred
        state_update['awaiting_location'] = False
        print(f"[LOCATION] Inferred and set location_preference to: {inferred}")

    # --- SEARCH INTENT & LOCATION PROMPT TIMING ---
    message_lower = latest_user_message.lower()
    search_trigger_keywords = ["clinic", "dentist", "recommend", "find", "looking", "search"]
    search_intent_detected = any(k in message_lower for k in search_trigger_keywords) or ('services' in current_filters)

    # 2) Only prompt for location once search intent is present
    if not location_preference and search_intent_detected:
        state_update['awaiting_location'] = True
        return {
            # Keep minimal text; UI should render buttons via meta
            "response": "Which country would you like to explore?",
            "meta": {"type": "location_prompt", "options": [
                {"key": "jb", "label": "Johor Bahru"},
                {"key": "sg", "label": "Singapore"},
                {"key": "both", "label": "Both"}
            ]},
            # Do not echo previous filters when prompting for location
            "applied_filters": {},
            "candidate_pool": [],
            "booking_context": {},
            "state_update": state_update
        }

    # If no location AND no search intent yet, just gently encourage specification (do not force prompt)
    if not location_preference and not search_intent_detected:
        return {
            "response": "Let me know a treatment you need (e.g., root canal, cleaning) or say you want to find a clinic—then I can help you narrow by country (SG vs JB).",
            "applied_filters": previous_filters,
            "candidate_pool": [],
            "booking_context": {},
            "state_update": state_update
        }

    # --- TABLE ROUTING BY LOCATION ---
    # jb -> clinics_data, sg -> sg_clinics, all -> union of both
    def build_query_for_table(table_name: str):
        return supabase.table(table_name).select('*')

    if location_preference == 'sg':
        db_queries = [('sg_clinics', build_query_for_table('sg_clinics'))]
    elif location_preference == 'jb':
        db_queries = [('clinics_data', build_query_for_table('clinics_data'))]
    else:
        db_queries = [
            ('clinics_data', build_query_for_table('clinics_data')),
            ('sg_clinics', build_query_for_table('sg_clinics')),
        ]

    if 'services' in final_filters:
        # Mapping for common service terms to correct columns
        service_column_map = {
            'scaling': 'general_dentistry',
            'cleaning': 'general_dentistry',
            'teeth cleaning': 'general_dentistry',
            'polishing': 'general_dentistry',
            'basic cleaning': 'general_dentistry',
            'checkup': 'general_dentistry',
            'veneers': ['composite_veneers', 'porcelain_veneers'],
            'dental exam': 'general_dentistry',
            'oral checkup': 'general_dentistry',
            'dental x-ray': 'general_dentistry',
            'fluoride treatment': 'general_dentistry',
            'dental sealant': 'general_dentistry',
            'pediatric dentistry': 'general_dentistry',
            'oral hygiene instruction': 'general_dentistry',
            'preventive care': 'general_dentistry',
            'tooth extraction': 'general_dentistry',
            'emergency dental care': 'general_dentistry',
            'space maintainer': 'general_dentistry',
            'mouthguard': 'general_dentistry',
            'dental consultation': 'general_dentistry',
            'dietary counseling': 'general_dentistry',
            'desensitization treatment': 'general_dentistry',
            'tooth remineralization': 'general_dentistry',
            'dental cleaning for children': 'general_dentistry',
            'halitosis treatment': 'general_dentistry',
            'tooth eruption monitoring': 'general_dentistry',
            'dental plaque removal': 'general_dentistry',
        }
        for service in final_filters['services']:

            # --- FIX: Sanitize the service name to match the database column format ---
            sanitized_service = service.replace(' ', '_')
            mapped_column = service_column_map.get(service.lower(), sanitized_service)
            # apply to all queries
            if isinstance(mapped_column, list):
                for i, (name, q) in enumerate(db_queries):
                    for col in mapped_column:
                        db_queries[i] = (name, q.eq(col, True))
            else:
                for i, (name, q) in enumerate(db_queries):
                    db_queries[i] = (name, q.eq(mapped_column, True))

    # --- COST LOOKUP / COMPARISON DETECTION ---
    # Simple mapping using proceduresData-like keys (lowercased) for cost queries
    cost_keywords = ["cost", "price", "how much", "expensive", "cheaper"]
    comparison_keywords = ["compare", "vs", "versus", "difference", "jb or sg", "sg or jb"]
    wants_cost = any(k in message_lower for k in cost_keywords)
    wants_comparison = any(k in message_lower for k in comparison_keywords)

    procedures_reference: Dict[str, Dict[str, str]] = {
        'dental cleaning': {'sg': '80 - 120', 'jb': '25 - 40'},
        'tooth filling': {'sg': '150 - 300', 'jb': '40 - 80'},
        'root canal': {'sg': '800 - 1500', 'jb': '200 - 400'},
        'dental crown': {'sg': '1200 - 2000', 'jb': '300 - 600'},
        'teeth whitening': {'sg': '400 - 800', 'jb': '100 - 200'},
        'dental implant': {'sg': '3000 - 5000', 'jb': '800 - 1500'},
        'wisdom tooth extraction': {'sg': '300 - 800', 'jb': '80 - 200'},
        'orthodontic braces': {'sg': '4000 - 8000', 'jb': '1200 - 2500'}
    }

    def normalize_procedure(text: str) -> Optional[str]:
        t = text.lower()
        for key in procedures_reference.keys():
            if key in t:
                return key
        return None

    # If user wants a general SG vs JB comparison (not price-specific)
    if wants_comparison and not wants_cost:
        comparison_payload = {
            'jb_pros': ["Significant savings (often 50-70%)", "Access to modern clinics", "Value for long multi-step treatments"],
            'jb_cons': ["Cross-border travel time", "Need to plan follow-ups across CIQ"],
            'sg_pros': ["High convenience / no travel", "MOH-accredited & easier follow-up", "Familiar standards"],
            'sg_cons': ["Higher treatment costs", "Savings opportunity missed for major work"],
        }
        response_lines = [
            "Here's a balanced view:",
            "\nJohor Bahru (JB) – Pros:", *[f" • {p}" for p in comparison_payload['jb_pros']],
            "JB – Cons:", *[f" • {c}" for c in comparison_payload['jb_cons']],
            "\nSingapore (SG) – Pros:", *[f" • {p}" for p in comparison_payload['sg_pros']],
            "SG – Cons:", *[f" • {c}" for c in comparison_payload['sg_cons']],
            "\nIf you tell me the treatment (e.g., root canal, implants), I can provide tailored price ranges and options. Would you like to proceed with a specific treatment?"
        ]
        return {
            "response": "\n".join(response_lines),
            "applied_filters": previous_filters,
            "candidate_pool": [],
            "booking_context": {},
            "state_update": state_update
        }

    # Price-specific question handling (returns ranges, does not fetch clinics yet)
    if wants_cost:
        proc_key = normalize_procedure(latest_user_message)
        if not proc_key and 'services' in current_filters:
            # try service enum value mapping
            possible_service = current_filters['services'][0].replace('_', ' ')
            proc_key = normalize_procedure(possible_service)
        if proc_key:
            ref = procedures_reference.get(proc_key)
            price_response = f"Estimated private clinic ranges for {proc_key.title()} — SG: {ref['sg']} S$, JB: {ref['jb']} S$. Savings can be substantial, but final costs depend on case complexity. Want me to find clinics for this treatment?"
        else:
            price_response = "I can give you SG vs JB price ranges if you mention a treatment (e.g., root canal, dental implant). What treatment are you considering?"
        return {
            "response": price_response,
            "applied_filters": previous_filters,
            "candidate_pool": [],
            "booking_context": {},
            "state_update": state_update
        }

    # --- FILTER REFINEMENT PROMPTS ---
    if search_intent_detected and not final_filters.get('services') and location_preference:
        return {
            "response": "Great — tell me which treatment you need (e.g., root canal, cleaning, implants) so I can narrow options.",
            "applied_filters": previous_filters,
            "candidate_pool": [],
            "booking_context": {},
            "state_update": state_update
        }
    
    township_filter = final_filters.get('township')
    # Treat 'singapore' / 'sg' as country-level, not township. Route to SG table and drop township filter
    if township_filter and township_filter.lower() in ['singapore', 'sg']:
        print("Detected Singapore as country-level; routing to SG clinics and removing township filter")
        location_preference = 'sg'
        state_update['location_preference'] = 'sg'
        final_filters.pop('township', None)
        township_filter = None
        db_queries = [('sg_clinics', build_query_for_table('sg_clinics'))]
    elif township_filter and township_filter.lower() in ['jb', 'johor bahru']:
        print("Applying Metro JB filter...")
        # Ensure we query JB table(s)
        if location_preference != 'jb':
            location_preference = 'jb'
            state_update['location_preference'] = 'jb'
            db_queries = [('clinics_data', build_query_for_table('clinics_data'))]
        for i, (name, q) in enumerate(db_queries):
            db_queries[i] = (name, q.eq('is_metro_jb', True))
    elif township_filter:
        print(f"Applying fuzzy township filter: {township_filter}")
        # Case-insensitive contains match to handle variants like 'Jurong' -> 'JURONG WEST', 'JURONG SPRING'
        pattern = f"%{township_filter}%"
        for i, (name, q) in enumerate(db_queries):
            try:
                db_queries[i] = (name, q.ilike('township', pattern))
            except Exception:
                # Fallback if client doesn't support ilike; keep equality (may be restrictive)
                db_queries[i] = (name, q.eq('township', township_filter))

    # After routing, attach normalized country into filters for consistency
    if location_preference:
        final_filters['country'] = 'SG' if location_preference == 'sg' else ('MY' if location_preference == 'jb' else 'SG+MY')

    print(f"Final Filters to be applied: {final_filters}")

    try:
        merged = []
        for name, q in db_queries:
            try:
                resp = q.execute()
                data = resp.data or []
                # annotate country if missing
                for c in data:
                    if 'country' not in c or not c['country']:
                        c['country'] = 'SG' if name == 'sg_clinics' else 'MY'
                merged.extend(data)
            except Exception as e:
                print(f"Database query error for table {name}: {e}")
        candidate_clinics = merged
        # If a fuzzy township was requested, also apply a lightweight in-memory filter to township/address just in case
        if township_filter:
            tf_low = township_filter.lower()
            filtered = [c for c in candidate_clinics if (c.get('township') and tf_low in str(c.get('township', '')).lower()) or (c.get('address') and tf_low in str(c.get('address', '')).lower())]
            if filtered:
                print(f"Fuzzy township post-filter reduced candidates from {len(candidate_clinics)} to {len(filtered)}")
                candidate_clinics = filtered
        print(f"Found {len(candidate_clinics)} candidates after initial database filtering across {len(db_queries)} source(s).")
    except Exception as e:
        print(f"Database query error: {e}")
        candidate_clinics = []
    
    qualified_clinics = []
    if candidate_clinics:
        quality_gated_clinics = [c for c in candidate_clinics if c.get('rating', 0) >= 4.5 and c.get('reviews', 0) >= 30]
        print(f"Found {len(quality_gated_clinics)} candidates after Quality Gate.")
        # --- FIX: THIS IS THE NEW, CORRECT SORTING LOGIC ---
        # Step 2: Sort the qualified clinics by the quality standard (best first).
        # We sort by rating (highest first), then by number of reviews (highest first) as a tie-breaker.
        quality_gated_clinics.sort(key=lambda c: (c.get('rating', 0), c.get('reviews', 0)), reverse=True)
        # --------------------------------------------------


        qualified_clinics = quality_gated_clinics

    top_clinics = []
    if qualified_clinics:
        top_clinics = qualified_clinics[:3]



# --- PASTE THIS NEW BLOCK IN ITS PLACE ---

    if not top_clinics:
        # Provide a more helpful response when no clinics are found
        print("DEBUG: No top clinics found, returning early.")
        return {"response": "I'm sorry, I couldn't find any clinics that match your specific criteria. Would you like to try a different search?", "applied_filters": final_filters, "candidate_pool": [], "booking_context": {}}

    context = json.dumps([{"position": i + 1, **{k: clinic.get(k) for k in ['name', 'address', 'rating', 'reviews', 'website_url', 'operating_hours']}} for i, clinic in enumerate(top_clinics)], indent=2)
 
    augmented_prompt = f'You are a Data Formatter. Your only job is to take the following JSON data and format it into a friendly, conversational, and easy-to-read summary for a user. Present the top 3 clinics clearly. Do not output raw JSON. **Data:**\n```json\n{context}\n```'

    
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

    # --- THIS IS THE FIX: Clean the vectors and add a debug print ---
    cleaned_candidate_pool = []
    # Simple sentiment-style tagging (rule-based) before returning
    def derive_tags(clinic: dict) -> List[str]:
        tags = []
        if clinic.get('rating', 0) >= 4.8: tags.append('Top Rated')
        if clinic.get('reviews', 0) >= 100: tags.append('High Review Volume')
        # Example service-based tags
        if clinic.get('dental_implant'): tags.append('Implant Focus')
        if clinic.get('porcelain_veneers') or clinic.get('composite_veneers'): tags.append('Cosmetic Friendly')
        return tags
    for clinic in top_clinics:
        clean_clinic = clinic.copy()
        clean_clinic.pop('embedding', None)
        clean_clinic.pop('embedding_arr', None)
        clean_clinic['tags'] = derive_tags(clean_clinic)
        cleaned_candidate_pool.append(clean_clinic)

    # Attach explicit country info for UI clarity
    if location_preference:
        final_filters['country'] = 'SG' if location_preference == 'sg' else ('MY' if location_preference == 'jb' else 'SG+MY')

    final_response_data = {
        "response": response_text, 
        "applied_filters": final_filters,
        "candidate_pool": cleaned_candidate_pool, # Use the new, clean list
        "booking_context": {}
    }

    # This line is our proof. It will print to your server log.
    print(f"DEBUG: Preparing to return {len(cleaned_candidate_pool)} clinics in the candidate pool.")

    if state_update:
        final_response_data["state_update"] = state_update

    return final_response_data