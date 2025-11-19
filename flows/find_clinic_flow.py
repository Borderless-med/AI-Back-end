import json
import string
import re
import google.generativeai as genai
from difflib import SequenceMatcher
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Tuple, Dict
from .utils import derive_clinic_tags

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

    # --- EARLY DIRECT CLINIC NAME LOOKUP (NEW) ---
    # If the user message appears to reference a specific clinic name (rather than asking for a search) we attempt
    # a direct name match before running the broader filtering logic. This prevents failures when a user asks
    # directly for details about "Some Dental Clinic" without providing a service. We bypass rating/review gates
    # for direct lookups to avoid hiding requested clinics.
    def attempt_direct_clinic_lookup(message: str):
        if not message:
            return None
        # Normalize unicode punctuation (curly quotes, weird spaces)
        lower = message.lower().strip()
        lower = lower.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
        lower = lower.replace('\u00a0', ' ')
        # Remove common filler prefixes to focus on the clinic name
        filler_prefixes = [
            "tell me all about ",
            "tell me about ",
            "show me ",
            "info on ",
            "information about ",
            "details on ",
            "learn about ",
            "more about ",
            "what about ",
        ]
        for fp in filler_prefixes:
            if lower.startswith(fp):
                lower = lower[len(fp):].strip()
                break

        # Simple typo corrections (common misspellings observed)
        TYPO_CORRECTIONS = {
            'dentel': 'dental',
            'dentl': 'dental',
            'denatl': 'dental',
            'ko ': 'koh ',  # beginning token
            ' ko dental': ' koh dental',
        }
        for wrong, right in TYPO_CORRECTIONS.items():
            if wrong in lower:
                lower = lower.replace(wrong, right)

        # Normalize brand patterns
        brand_patterns = {
            'q & m': 'q & m dental',
            'q&m': 'q & m dental',
            'q and m': 'q & m dental',
            'q  m': 'q & m dental',
        }
        for pat, canon in brand_patterns.items():
            if pat in lower:
                # Only extend if 'dental' not already present
                if 'dental' not in lower:
                    lower = lower.replace(pat, canon)

        # Brand special-case: Q & M brand may lack distinct tokens beyond generic words
        qm_brand = bool(re.search(r"\bq\s*(?:&|and|\&)\s*m\b", lower))

        # Heuristics: short-ish message or contains explicit name markers
        trigger_keywords = ["clinic", "dental", "centre", "center"]
        # Avoid triggering on purely generic search words without a distinctive token
        generic_only = {"find", "recommend", "suggest", "clinic", "clinics", "dentist", "dental", "near", "nearby", "and", "&", "smile", "hub", "care", "plus", "lounge", "surgery", "medical", "center", "centre", "the"}
        country_tokens = {"jb", "johor", "johor bahru", "singapore", "sg"}
        tokens = [t for t in [tok.strip('.,:;!"\'') for tok in lower.split()] if t]
        distinct_tokens = [t for t in tokens if t not in generic_only and t not in country_tokens]
        # If this is clearly a Q & M brand query, allow proceeding even if distinct tokens are empty
        if not distinct_tokens and not qm_brand:
            return None
        # Require at least one trigger word or message length < 60 indicating a singular target request
        if not any(k in lower for k in trigger_keywords) and len(lower) > 60:
            return None
        # Build a fuzzy name fragment from remaining tokens (exclude very short tokens)
        name_fragment = " ".join([t for t in distinct_tokens if len(t) >= 2])  # allow short brand tokens like 'ko'
        if len(name_fragment) < 3:
            # If brand-only query like "q & m (dental)", synthesize a fragment
            if qm_brand:
                name_fragment = "q & m dental"
            else:
                return None
        # Choose tables by explicit country hints when present; otherwise query both.
        has_jb_hint = any(k in lower for k in ["jb","johor","johor bahru","bahru"])
        has_sg_hint = any(k in lower for k in ["singapore","sg","s'g","lion city"]) and not has_jb_hint
        if has_jb_hint:
            tables = ["clinics_data"]
        elif has_sg_hint:
            tables = ["sg_clinics"]
        else:
            tables = ["clinics_data", "sg_clinics"]

        # If Q & M brand query, fetch all matching branches and pick best
        if qm_brand:
            brand_matches = []
            qm_patterns = ["%q & m%", "%q&m%", "%q and m%"]
            for tbl in tables:
                for pat in qm_patterns:
                    try:
                        resp = supabase.table(tbl).select("*").ilike("name", pat).execute()
                        data = resp.data or []
                        for c in data:
                            if 'country' not in c or not c['country']:
                                c['country'] = 'SG' if tbl == 'sg_clinics' else 'MY'
                        brand_matches.extend(data)
                    except Exception as e:
                        print(f"[DirectLookup] Q&M query error on {tbl} with pattern {pat}: {e}")
            # Deduplicate by id or name
            seen_b = set(); deduped_b = []
            for c in brand_matches:
                key = c.get('id') or c.get('name')
                if key not in seen_b:
                    deduped_b.append(c); seen_b.add(key)
            brand_matches = deduped_b
            if not brand_matches:
                print("[DirectLookup] No Q & M branches found for brand query.")
            else:
                # Pick best by rating, then reviews
                brand_matches.sort(key=lambda c: (c.get('rating', 0) or 0, c.get('reviews', 0) or 0), reverse=True)
                clinic = brand_matches[0]
                clinic_clean = {k: v for k, v in clinic.items() if k not in {"embedding", "embedding_arr"}}
                clinic_clean['tags'] = derive_clinic_tags(clinic_clean)
                address = clinic_clean.get('address')
                if address:
                    from urllib.parse import quote_plus
                    clinic_clean['maps_link'] = f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(address)}"
                response_text = (
                    f"Clinic details for **{clinic_clean.get('name','Unknown Clinic')}**:\n"
                    f"Address: {address or 'Not available'}\n"
                    f"Rating: {clinic_clean.get('rating','N/A')} ({clinic_clean.get('reviews','N/A')} reviews)\n"
                    f"Country: {clinic_clean.get('country','Unknown')}\n"
                    + ("\nThere are multiple Q & M branches. If you meant a different one, tell me the area (e.g., Yishun, Bedok).")
                )
                print(f"[DirectLookup] Q&M brand matched: {clinic_clean.get('name')} ({clinic_clean.get('country')})")
                country = clinic_clean.get('country')
                loc_pref = 'sg' if country == 'SG' else ('jb' if country == 'MY' else None)
                state_update_local = {"location_preference": loc_pref, "awaiting_location": False} if loc_pref else {}
                return {
                    "response": response_text,
                    "applied_filters": {"direct_clinic": clinic_clean.get('name'), "country": clinic_clean.get('country')},
                    "candidate_pool": [clinic_clean],
                    "booking_context": {},
                    "meta": {"type": "clinic_detail"},
                    "state_update": state_update_local
                }

        # Try chosen tables; use ilike for case-insensitive substring match
        matched = []
        print(f"[DirectLookup] Trying direct name match for fragment: '{name_fragment}' in tables: {tables}")
        for tbl in tables:
            try:
                resp = supabase.table(tbl).select("*").ilike("name", f"%{name_fragment}%").execute()
                data = resp.data or []
                # Annotate country if missing
                for c in data:
                    if 'country' not in c or not c['country']:
                        c['country'] = 'SG' if tbl == 'sg_clinics' else 'MY'
                matched.extend(data)
            except Exception as e:
                print(f"[DirectLookup] Query error on {tbl}: {e}")
        # If no results with the full fragment, try token-wise queries to be tolerant to typos/extra words
        if not matched:
            for tok in distinct_tokens:
                if len(tok) < 3:
                    continue
                for tbl in tables:
                    try:
                        resp = supabase.table(tbl).select("*").ilike("name", f"%{tok}%").execute()
                        data = resp.data or []
                        for c in data:
                            if 'country' not in c or not c['country']:
                                c['country'] = 'SG' if tbl == 'sg_clinics' else 'MY'
                        matched.extend(data)
                    except Exception as e:
                        print(f"[DirectLookup] Token query error on {tbl} for '{tok}': {e}")
            # Deduplicate by id or name
            seen = set()
            deduped = []
            for c in matched:
                key = c.get('id') or c.get('name')
                if key not in seen:
                    deduped.append(c)
                    seen.add(key)
            matched = deduped
        if not matched:
            # Fallback fuzzy scan: pull limited set of clinic names from relevant tables and compute similarity
            fuzzy_pool = []
            for tbl in tables:
                try:
                    # Select only columns that exist across tables; annotate country below
                    resp = supabase.table(tbl).select("id,name,address,rating,reviews,website_url,operating_hours,is_metro_jb").limit(200).execute()
                    data = resp.data or []
                    for c in data:
                        if 'country' not in c or not c['country']:
                            c['country'] = 'SG' if tbl == 'sg_clinics' else 'MY'
                    fuzzy_pool.extend(data)
                except Exception as e:
                    print(f"[DirectLookup] Fuzzy pool query error on {tbl}: {e}")
            # Score by similarity to cleaned message stripped of country tokens
            def clean_for_similarity(text: str) -> str:
                for ct in country_tokens:
                    text = text.replace(ct, '')
                return text.strip()
            target = clean_for_similarity(lower)
            # Require at least one meaningful non-generic token in target for fuzzy match
            GENERIC_NAME_TOKENS = {"dental", "clinic", "dentist", "center", "centre", "care", "smile", "plus", "the", "and", "&", "surgery", "medical", "family", "oral", "health", "lounge", "group"}
            target_tokens = {t for t in [tok.strip('.,:;!"\'') for tok in target.split()] if t and t not in GENERIC_NAME_TOKENS and t not in country_tokens and len(t) >= 3}
            if not target_tokens and not qm_brand:
                print("[DirectLookup] Fuzzy fallback aborted: no meaningful tokens in target.")
                return None
            best_c = None
            best_score = 0.0
            for c in fuzzy_pool:
                n = c.get('name', '').lower()
                # Skip candidates with zero overlap on meaningful tokens
                name_tokens = {t for t in [tok.strip('.,:;!"\'') for tok in n.split()] if t and t not in GENERIC_NAME_TOKENS and len(t) >= 3}
                if target_tokens and not (target_tokens & name_tokens):
                    continue
                sim = SequenceMatcher(None, target, n).ratio()
                if sim > best_score:
                    best_score = sim
                    best_c = c
            if best_c and best_score >= 0.82:
                matched = [best_c]
                print(f"[DirectLookup] Fuzzy fallback matched '{best_c.get('name')}' with sim={best_score:.2f}")
            else:
                print(f"[DirectLookup] Fuzzy fallback found no clinic above threshold (best={best_score:.2f})")
                # Since this path was triggered as a likely direct-name request, do NOT fall back to generic search.
                # Provide a clear no-match message and preserve any inferred country preference.
                hint = " in Johor Bahru (JB)" if has_jb_hint else (" in Singapore (SG)" if has_sg_hint else "")
                friendly = (
                    f"I couldn’t find a clinic named '{name_fragment}'{hint}. "
                    f"If you want, I can search by treatment instead (e.g., root canal, cleaning)."
                )
                state_update_local = {}
                if has_jb_hint:
                    state_update_local = {"location_preference": 'jb', "awaiting_location": False}
                elif has_sg_hint:
                    state_update_local = {"location_preference": 'sg', "awaiting_location": False}
                return {
                    "response": friendly,
                    "applied_filters": {},
                    "candidate_pool": [],
                    "booking_context": {},
                    "meta": {"type": "no_direct_match"},
                    "state_update": state_update_local
                }
        # Prefer exact-ish matches first (token containment), then fall back to first result
        GENERIC_NAME_TOKENS = {"dental", "clinic", "dentist", "center", "centre", "care", "smile", "plus", "the", "and", "&", "surgery", "medical", "family", "oral", "health", "lounge", "group"}
        meaningful_tokens = [t for t in distinct_tokens if t not in GENERIC_NAME_TOKENS]
        def score(clinic):
            n = clinic.get('name', '').lower()
            token_hits = sum(1 for t in distinct_tokens if t in n)
            meaningful_hits = sum(1 for t in meaningful_tokens if t in n)
            sim = SequenceMatcher(None, name_fragment, n).ratio()
            # Weighted score: prioritize token containment, then similarity
            return (token_hits * 1.0) + (meaningful_hits * 1.5) + (sim * 2.0)
        matched.sort(key=score, reverse=True)
        best = matched[0]
        best_tokens = sum(1 for t in distinct_tokens if t in best.get('name', '').lower())
        best_meaningful = sum(1 for t in meaningful_tokens if t in best.get('name', '').lower())
        best_sim = SequenceMatcher(None, name_fragment, best.get('name', '').lower()).ratio()
        # Require at least one meaningful token hit OR strong similarity (>= 0.80)
        if best_meaningful < 1 and best_sim < 0.80:
            print(f"[DirectLookup] Fuzzy match below threshold (tokens={best_tokens}, sim={best_sim:.2f}); aborting direct lookup.")
            return None
        clinic = best
        # Clean embedding fields if present
        clinic_clean = {k: v for k, v in clinic.items() if k not in {"embedding", "embedding_arr"}}
        clinic_clean['tags'] = derive_clinic_tags(clinic_clean)
        # Provide a Google Maps direction link stub if address present (origin left blank for front-end user input)
        address = clinic_clean.get('address')
        if address:
            from urllib.parse import quote_plus
            clinic_clean['maps_link'] = f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(address)}"
        response_text = (
            f"Clinic details for **{clinic_clean.get('name','Unknown Clinic')}**:\n"
            f"Address: {address or 'Not available'}\n"
            f"Rating: {clinic_clean.get('rating','N/A')} ({clinic_clean.get('reviews','N/A')} reviews)\n"
            f"Country: {clinic_clean.get('country','Unknown')}\n"
            + ("\nYou can start a booking by telling me you want to book here, or ask for travel directions."))
        # Provide state_update so downstream logic can remember country preference
        country = clinic_clean.get('country')
        loc_pref = 'sg' if country == 'SG' else ('jb' if country == 'MY' else None)
        state_update_local = {}
        if loc_pref:
            state_update_local = {"location_preference": loc_pref, "awaiting_location": False}
        print(f"[DirectLookup] Clinic matched: {clinic_clean.get('name')} ({clinic_clean.get('country')}) with score {score(best):.2f}")
        return {
            "response": response_text,
            "applied_filters": {"direct_clinic": clinic_clean.get('name'), "country": clinic_clean.get('country')},
            "candidate_pool": [clinic_clean],
            "booking_context": {},
            "meta": {"type": "clinic_detail"},
            "state_update": state_update_local
        }

    direct_clinic_result = attempt_direct_clinic_lookup(latest_user_message)
    if direct_clinic_result:
        return direct_clinic_result

    # Known township-to-country hints to improve inference and avoid wrong-table queries
    TOWNSHIP_COUNTRY_MAP = {
        # Singapore regions
        'jurong': 'sg', 'jurong east': 'sg', 'jurong west': 'sg', 'bedok': 'sg', 'chinatown': 'sg',
        'toa payoh': 'sg', 'ang mo kio': 'sg', 'yishun': 'sg', 'tampines': 'sg', 'pasir ris': 'sg',
        # Johor Bahru (Malaysia) areas
        'taman molek': 'jb', 'molek': 'jb', 'mount austin': 'jb', 'austin heights': 'jb', 'taman mount austin': 'jb',
        'tebrau': 'jb', 'add a': 'jb', 'adda heights': 'jb', 'bukit indah': 'jb', 'permas jaya': 'jb',
        'skudai': 'jb', 'taman sutera': 'jb', 'taman pelangi': 'jb', 'taman johor jaya': 'jb',
        'taman damansara aliff': 'jb', 'damansara aliff': 'jb', 'taman setia indah': 'jb', 'setia indah': 'jb',
    }

    def detect_country_from_township(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        t = text.lower()
        # substring containment to catch variants (e.g., "jurong" matches "jurong west")
        for key, country in TOWNSHIP_COUNTRY_MAP.items():
            if key in t:
                return country
        return None
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
                if args.get('service'):
                    # Multi-service stacking: merge with previous filters if present
                    extracted = args.get('service')
                    prior_services = []
                    if isinstance(previous_filters, dict) and 'services' in previous_filters and isinstance(previous_filters['services'], list):
                        prior_services = previous_filters['services']
                    merged = list(dict.fromkeys([*(prior_services or []), extracted]))  # de-duplicate preserving order
                    current_filters['services'] = merged
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
        if 'services' not in current_filters:
            current_filters['services'] = [heuristic_svc]
            print(f"[Heuristic] Service set to '{heuristic_svc}' from user text fallback")
        else:
            # Add if not already present
            if heuristic_svc not in current_filters['services']:
                current_filters['services'].append(heuristic_svc)
                print(f"[Heuristic] Added additional service '{heuristic_svc}' (multi-service stacking)")

    if 'township' in current_filters and current_filters['township']:
        current_filters['township'] = current_filters['township'].rstrip(string.punctuation).strip()
        print(f"Sanitized township to: '{current_filters['township'].lower()}'")
        # If the LLM extracted a generic/country-level area (e.g., 'Singapore' or 'Johor Bahru')
        # but the user's text contains a more specific township (e.g., 'Taman Molek'), prefer the specific one.
        generic_aliases = { 'singapore', 'sg', 'johor', 'jb', 'johor bahru' }
        if current_filters['township'].lower() in generic_aliases:
            ht = heuristic_township_from_text(latest_user_message)
            if ht and ht.lower() not in generic_aliases:
                current_filters['township'] = ht.rstrip(string.punctuation).strip()
                print(f"[Heuristic Override] Replaced generic township with specific '{current_filters['township']}' from text")
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
        # Infer from township keywords present in free text
        mapped = detect_country_from_township(t)
        if mapped:
            return mapped
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
        # If a township clearly implies a country, override the location_preference accordingly
        implied = detect_country_from_township(township_filter)
        if implied and implied != location_preference:
            print(f"[LOCATION] Township '{township_filter}' implies country '{implied}'. Overriding location_preference.")
            location_preference = implied
            state_update['location_preference'] = implied
            # reset db_queries to match new location
            if implied == 'sg':
                db_queries = [('sg_clinics', build_query_for_table('sg_clinics'))]
            elif implied == 'jb':
                db_queries = [('clinics_data', build_query_for_table('clinics_data'))]
        # Do NOT narrow in SQL by township; we'll perform a robust in-memory fuzzy filter on township/address
        print(f"Applying fuzzy township filter (in-memory): {township_filter}")

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
        # If a fuzzy township was requested, apply a robust in-memory filter to township and address
        if township_filter:
            tf_low = township_filter.lower()
            filtered = [c for c in candidate_clinics if (c.get('township') and tf_low in str(c.get('township', '')).lower()) or (c.get('address') and tf_low in str(c.get('address', '')).lower())]
            if filtered:
                print(f"Fuzzy township post-filter reduced candidates from {len(candidate_clinics)} to {len(filtered)}")
                candidate_clinics = filtered
            else:
                print("Fuzzy township post-filter found 0 matches — keeping broader country/service results to avoid empty response.")
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
 
    augmented_prompt = (
        'You are a Data Formatter. Your only job is to take the following JSON data and format it into a friendly, conversational, and easy-to-read summary for a user. '
        'Present the top 3 clinics clearly. Start with a one-line explanation: "Top 3 clinics chosen by rating and review volume." '
        'Do not output raw JSON. **Data:**\n```json\n' + context + '\n```'
    )

    
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
        
        response_text = (
            "Top 3 clinics chosen by rating and review volume.\n\n"
            + "I found a few highly-rated clinics for you:\n" + "\n".join(fallback_list)
            + "\n\nWould you like to book an appointment at one of these locations?"
        )

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
        "candidate_pool": cleaned_candidate_pool,  # Use the new, clean list
        "booking_context": {}
    }

    # This line is our proof. It will print to your server log.
    print(f"DEBUG: Preparing to return {len(cleaned_candidate_pool)} clinics in the candidate pool.")

    if state_update:
        final_response_data["state_update"] = state_update

    return final_response_data