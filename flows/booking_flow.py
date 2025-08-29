import json
from urllib.parse import urlencode
from pydantic import BaseModel, Field
from typing import Optional, List

# --- Pydantic Models required for this flow ---
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

# --- Helper function for capturing user details ---
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
                return {"response": final_response_text, "applied_filters": {}, "candidate_pool": [], "booking_context": {"status": "complete"}}
    except Exception as e:
        print(f"Booking Info Capture Exception: {e}")
        return {"response": "I'm sorry, I had trouble capturing those details. Please try again.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}

# --- The main handler function for this flow ---
def handle_booking_flow(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model):
    if booking_context.get("status") == "confirming_details":
        try:
            pre_check_prompt = f'You are a JSON validation expert. Your only job is to determine if the user\'s message contains personal contact information. You MUST respond with a single, valid JSON object: {{"has_info": boolean}}.\nExamples:\n- User Message: "My name is John" -> Your Response: {{"has_info": true}}\n- User Message: "yes that is correct" -> Your Response: {{"has_info": false}}\nAnalyze this message: "{latest_user_message}"'
            user_info_check_response = factual_brain_model.generate_content(pre_check_prompt)
            check_result = json.loads(user_info_check_response.text.strip().replace("```json", "").replace("```", ""))
            if check_result.get("has_info"):
                print("In Booking Mode: User provided info directly. Capturing details...")
                booking_context["status"] = "gathering_info"
                return capture_user_info(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)
        except Exception as e:
            print(f"Booking info pre-check failed: {e}")

        print("In Booking Mode: Processing user confirmation...")
        try:
            confirmation_response = factual_brain_model.generate_content(f"Analyze the user's reply for confirmation and corrections. Reply: '{latest_user_message}'", tools=[Confirmation])
            function_call = confirmation_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args:
                confirm_args = function_call.args
                if confirm_args.get("is_confirmed"):
                    booking_context["status"] = "gathering_info"
                    response_text = "Perfect. To pre-fill the form for you, what is your **full name, email address, and WhatsApp number**?"
                    return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
                else:
                    if confirm_args.get("corrected_treatment") or confirm_args.get("corrected_clinic"):
                        if confirm_args.get("corrected_treatment"): booking_context["treatment"] = confirm_args.get("corrected_treatment")
                        if confirm_args.get("corrected_clinic"): booking_context["clinic_name"] = confirm_args.get("corrected_clinic")
                        response_text = f"Got it, thank you for clarifying. So that's an appointment for **{booking_context['treatment']}** at **{booking_context['clinic_name']}**. Is that correct?"
                        return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
                    else:
                        response_text = "My apologies. Let's start over. What can I help you with?"
                        return {"response": response_text, "applied_filters": {}, "candidate_pool": [], "booking_context": {}}
        except Exception as e:
            print(f"Booking Confirmation Error: {e}")
            return {"response": "Sorry, I had a little trouble understanding. Please confirm with a 'yes' or 'no', or let me know what you'd like to change.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": booking_context}
    
    elif booking_context.get("status") == "gathering_info":
        print("In Booking Mode: Capturing user info...")
        return capture_user_info(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)

    else:
        print("Starting Booking Mode...")
        try:
            booking_intent_response = factual_brain_model.generate_content(f"Extract the name of the dental clinic from the user's message. Message: '{latest_user_message}'", tools=[BookingIntent])
            function_call = booking_intent_response.candidates[0].content.parts[0].function_call
            if function_call and function_call.args and function_call.args.get('clinic_name'):
                clinic_name = function_call.args.get('clinic_name')
                treatment = (previous_filters.get('services') or ["a consultation"])[0]
                new_booking_context = {"status": "confirming_details", "clinic_name": clinic_name, "treatment": treatment}
                response_text = f"Great! I can help you get started with booking. Just to confirm, are you looking to book an appointment for **{treatment}** at **{clinic_name}**?"
                return {"response": response_text, "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": new_booking_context}
            else:
                print("Booking Intent Extraction Failed: No clinic name found.")
                return {"response": "I can help with booking an appointment. Please let me know the name of the clinic you're interested in.", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}}
        except Exception as e:
            print(f"Booking Intent Extraction Error: {e}")
            return {"response": "I can help with that. Which clinic would you like to book?", "applied_filters": previous_filters, "candidate_pool": candidate_clinics, "booking_context": {}}