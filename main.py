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

# (All the code above this function is the same)

@app.post("/chat")
def handle_chat(query: UserQuery):
    # (All the logic before booking mode is the same)

    # --- BOOKING MODE LOGIC ---
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
                
                # THE FINAL FIX: Using the correct Lovable URL for the demo.
                base_url = "https://lovable.dev/projects/20b0e962-1b25-40eb-b514-5b283d2a150d"
                
                clinic_name_safe = urlencode({'q': booking_context.get('clinic_name', '')})[2:]
                
                params = {
                    'name': user_args.get('patient_name'),
                    'email': user_args.get('email_address'),
                    'phone': user_args.get('whatsapp_number'),
                    'clinic': clinic_name_safe,
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
            # (rest of the booking error handling is the same)

    # (The rest of the file is the same)