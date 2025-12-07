import json
import re
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from typing import Optional

# --- Pydantic Models (no changes needed here) ---
class BookingIntent(BaseModel):
    clinic_name: str = Field(..., description="The name of the dental clinic the user wants to book.")

class UserInfo(BaseModel):
    patient_name: str = Field(..., description="The user's full name.")
    email_address: str = Field(..., description="The user's email address.")
    whatsapp_number: str = Field(..., description="The user's WhatsApp number, including country code if provided.")
    
class Confirmation(BaseModel):
    is_confirmed: bool = Field(..., description="True if the user confirms ('yes', 'correct'), false if they deny or want to change something.")
    corrected_treatment: Optional[str] = Field(None, description="If the user wants a different treatment, extract the new treatment name.")
    corrected_clinic: Optional[str] = Field(None, description="If the user wants to book at a different clinic, extract the new clinic name.")

# --- Helper function: Detect cancellation intent using AI ---
def detect_cancellation_intent(user_message, factual_brain_model):
    """
    Uses AI to detect if the user wants to cancel/abort the booking.
    Returns True if cancellation intent detected, False otherwise.
    """
    try:
        prompt = f"""You are an intent classification expert. Your only job is to determine if the user wants to CANCEL or ABORT the booking process.
        
You MUST respond with a single, valid JSON object: {{"wants_to_cancel": boolean}}

Examples:
- "abort booking" -> {{"wants_to_cancel": true}}
- "changed my mind" -> {{"wants_to_cancel": true}}
- "I'll call them instead" -> {{"wants_to_cancel": true}}
- "never mind" -> {{"wants_to_cancel": true}}
- "go back" -> {{"wants_to_cancel": true}}
- "start over" -> {{"wants_to_cancel": true}}
- "actually, I want scaling instead" -> {{"wants_to_cancel": false}} (correction, not cancellation)
- "yes that's correct" -> {{"wants_to_cancel": false}}

Analyze this message: "{user_message}"
"""
        response = factual_brain_model.generate_content(prompt)
        result = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        return result.get("wants_to_cancel", False)
    except Exception as e:
        print(f"Cancellation intent detection error: {e}")
        return False

# --- V11 FIX: Extract treatment from explicit user mentions ---
def extract_treatment_from_message(user_message, factual_brain_model):
    """
    Extract treatment/service if user explicitly mentions 'for X', 'need X', or 'X at clinic'.
    Returns treatment name or None.
    """
    try:
        prompt = f"""Extract the dental service from this booking request, if explicitly mentioned.
        
You MUST respond with a single, valid JSON object: {{"service": string or null}}

Rules:
- Only extract if the user explicitly mentions a service in their booking request
- Map to standard service names: scaling, root_canal, braces, dental_implant, teeth_whitening, tooth_filling, dental_crown, wisdom_tooth, veneers, etc.
- Return null if no service is mentioned

Examples:
- "Book for braces at Aura Dental" -> {{"service": "braces"}}
- "I need root canal at Casa Dental" -> {{"service": "root_canal"}}
- "Book scaling at Mount Austin" -> {{"service": "scaling"}}
- "Book the first clinic" -> {{"service": null}}
- "Book clinic 2" -> {{"service": null}}

User message: "{user_message}"
"""
        response = factual_brain_model.generate_content(prompt)
        result_text = response.text.strip()
        # Remove markdown code fences if present, robust to single-line or no-newline outputs
        if result_text.startswith('```'):
            lines = result_text.split('\\n')
            if len(lines) >= 3:
                # Typical fenced block: first and last lines are fences
                result_text = '\\n'.join(lines[1:-1]).strip()
            else:
                # Fallback: just strip fence markers
                result_text = result_text.replace('```json', '').replace('```', '').strip()
        result = json.loads(result_text)
        service = result.get("service")
        if service:
            print(f"[V11 FIX] Extracted explicit treatment from user message: {service}")
        return service
    except Exception as e:
        print(f"[V11 FIX] Treatment extraction error: {e}")
        return None

# --- Helper function for capturing user details (no changes needed here) ---
def capture_user_info(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model):
    try:
        extraction_prompt = f"""
        You are an expert data extraction AI. Your only job is to analyze the user's message and populate the `UserInfo` tool.
        You must call the `UserInfo` tool. Do not respond with any other text.
        Examples:
        - User: "my name is John Doe, email is john@test.com, phone is 12345" -> Your action: UserInfo(patient_name='John Doe', email_address='john@test.com', whatsapp_number='12345')
        Analyze this message: "{latest_user_message}"
        """
        user_info_response = factual_brain_model.generate_content(extraction_prompt, tools=[UserInfo])
        
        if user_info_response.candidates and user_info_response.candidates[0].content.parts:
            function_call = user_info_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args:
                user_args = function_call.args
                base_url = "https://sg-smile-saver.vercel.app/book-now"
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
                return {"response": final_response_text, "applied_filters": {}, "candidate_pool": [], "booking_context": {"status": "complete"}}
    except Exception as e:
        print(f"Booking Info Capture Exception: {e}")
        return {"response": "I'm sorry, I had trouble capturing those details. Please try again.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}

# --- THIS IS THE NEW, SMARTER handle_booking_flow FUNCTION ---
def handle_booking_flow(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model, session_state=None):
    
    # --- STAGE 3: CAPTURING USER INFO ---
    if booking_context.get("status") == "gathering_info":
        print("In Booking Mode: Capturing user info...")
        return capture_user_info(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)

    # --- STAGE 2: CONFIRMING DETAILS (WITH NEW DETERMINISTIC LOGIC) ---
    if booking_context.get("status") == "confirming_details":
        print("In Booking Mode: Processing user confirmation...")
        
        # --- START: DETERMINISTIC CHECK ---
        user_reply = latest_user_message.strip().lower()
        affirmative_responses = ['yes', 'yep', 'yeah', 'ya', 'ok', 'confirm', 'correct', 'proceed', 'sounds good', 'do it', 'sure', 'alright']
        
        # V11 FIX 3: Use AI-based cancellation intent detection instead of keyword matching
        if detect_cancellation_intent(latest_user_message, factual_brain_model):
            print(f"[V11 FIX] AI detected cancellation intent. Resetting flow. User reply: {user_reply}")
            response_text = "Okay, I've cancelled that booking request. How else can I help you today?"
            return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}}

        if user_reply in affirmative_responses:
            print("[DETERMINISTIC] User confirmed. Moving to gathering_info.")
            booking_context["status"] = "gathering_info"
            response_text = "Perfect. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
            return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
        
        # --- END: DETERMINISTIC CHECK ---

        # --- FALLBACK: If not a simple yes/no, let the AI try to figure out corrections ---
        print("[AI FALLBACK] User response was not a simple yes/no. Checking for corrections.")
        try:
            # Check if user is trying to provide info directly instead of confirming
            pre_check_prompt = f'You are a JSON validation expert. Your only job is to determine if the user\'s message contains personal contact information. You MUST respond with a single, valid JSON object: {{"has_info": boolean}}.\nExamples:\n- User Message: "My name is John" -> Your Response: {{"has_info": true}}\n- User Message: "yes that is correct" -> Your Response: {{"has_info": false}}\nAnalyze this message: "{latest_user_message}"'
            user_info_check_response = factual_brain_model.generate_content(pre_check_prompt)
            check_result = json.loads(user_info_check_response.text.strip().replace("```json", "").replace("```", ""))
            if check_result.get("has_info"):
                print("In Booking Mode: User provided info directly. Capturing details...")
                booking_context["status"] = "gathering_info"
                return capture_user_info(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)

            confirmation_response = factual_brain_model.generate_content(f"Analyze the user's reply for confirmation and corrections. Reply: '{latest_user_message}'", tools=[Confirmation])
            function_call = confirmation_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args:
                confirm_args = function_call.args
                # Note: The is_confirmed check is now redundant due to our deterministic check, but we leave it for complex cases
                if confirm_args.get("corrected_treatment") or confirm_args.get("corrected_clinic"):
                    if confirm_args.get("corrected_treatment"): booking_context["treatment"] = confirm_args.get("corrected_treatment")
                    if confirm_args.get("corrected_clinic"): booking_context["clinic_name"] = confirm_args.get("corrected_clinic")
                    response_text = f"Got it, thank you for clarifying. So that's an appointment for **{booking_context['treatment']}** at **{booking_context['clinic_name']}**. Is that correct?"
                    return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
                else:
                    # If AI gets confused, it's safer to ask again
                    raise ValueError("AI could not determine a correction.")
        except Exception as e:
            print(f"Booking Confirmation Fallback Error: {e}")
            return {"response": "Sorry, I had a little trouble understanding. Please confirm with a 'yes' or 'no', or let me know what you'd like to change.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
        
    # --- STAGE 1: IDENTIFYING THE CLINIC ---
    print("Starting Booking Mode...")
    clinic_name = None

    # V9 FIX 1: ALWAYS pull treatment from filters FIRST (even if booking_context exists)
    # This fixes the issue where frontend sends empty booking_context after navigation
    # V11 FIX 2: Use services[-1] to get the LATEST treatment selection, not the first
    treatment_from_filters = previous_filters.get('services', [None])[-1] if previous_filters.get('services') else None
    if not booking_context.get("treatment") and treatment_from_filters:
        booking_context["treatment"] = treatment_from_filters
        print(f"[V9 FIX] Pulled treatment from previous_filters: {treatment_from_filters}")

    # Check if user already selected a clinic in previous turn (context preservation)
    if booking_context.get("selected_clinic_name"):
        clinic_name = booking_context.get("selected_clinic_name")
        print(f"Preserving previously selected clinic from context: {clinic_name}")
    # Check for implicit reference ("book here", "this one", etc.)
    elif session_state and any(word in latest_user_message.lower() for word in ['here', 'this one', 'this clinic', 'that one']):
        last_shown = session_state.get('last_shown_clinic')
        if last_shown:
            clinic_name = last_shown.get('name')
            print(f"[IMPLICIT REF] Detected '{latest_user_message}' → Using last shown clinic: {clinic_name}")
    elif candidate_clinics and len(candidate_clinics) > 0:
        pos_map = {'first': 0, '1st': 0, 'second': 1, '2nd': 1, 'third': 2, '3rd': 2, 'last': -1}
        ordinal_out_of_bounds = False
        for word, index in pos_map.items():
            if re.search(r'\b' + word + r'\b', latest_user_message):
                try:
                    clinic_name = candidate_clinics[index]['name']
                    print(f"Found positional reference '{word}'. Selected clinic: {clinic_name}")
                    break
                except IndexError:
                    ordinal_out_of_bounds = True
                    actual_count = len(candidate_clinics)
                    print(f"Positional reference '{word}' found, but index is out of bounds for candidate pool (only {actual_count} clinics available).")
                    # Return helpful error message
                    return {
                        "response": f"I only showed you {actual_count} clinic{'s' if actual_count != 1 else ''}. Please choose from 1 to {actual_count}, or specify the clinic name directly.",
                        "applied_filters": previous_filters,
                        "candidate_pool": candidate_clinics,
                        "booking_context": booking_context
                    }
    
    if not clinic_name:
        print("No positional reference found. Using AI to extract clinic name.")
        try:
            booking_intent_response = factual_brain_model.generate_content(f"Extract the name of the dental clinic from the user's message. Message: '{latest_user_message}'", tools=[BookingIntent])
            function_call = booking_intent_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args and function_call.args.get('clinic_name'):
                clinic_name = function_call.args.get('clinic_name')
        except Exception as e:
            print(f"Booking Intent Extraction Error: {e}")

    if clinic_name:
        # V11 FIX: Extract treatment from user message first (e.g., "Book for braces at Aura")
        explicit_treatment = extract_treatment_from_message(latest_user_message, factual_brain_model)
        
        # V11 FIX: Use services[-1] to get the LATEST treatment, not the first
        # Priority: explicit mention > latest from filters > default consultation
        treatment = explicit_treatment or (previous_filters.get('services') or ["a consultation"])[-1]
        
        new_booking_context = {"status": "confirming_details", "clinic_name": clinic_name, "treatment": treatment, "selected_clinic_name": clinic_name}
        response_text = f"Great! I can help you get started with booking. Just to confirm, are you looking to book an appointment for **{treatment}** at **{clinic_name}**?"
        return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": new_booking_context}
    else:
        print("Booking Intent Extraction Failed: No clinic name found.")
        return {"response": "I can help with booking an appointment. Please let me know the name of the clinic you're interested in.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}}