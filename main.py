import sys
print(f"--- PYTHON VERSION CHECK --- : {sys.version}")
import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional
import logging

# --- Import all four of our new, separated flow handlers ---
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.outofscope_flow import handle_out_of_scope

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY") # This MUST be your service_role key
supabase: Client = create_client(supabase_url, supabase_key)

# --- Define AI Models (Centralized) ---
gatekeeper_model = genai.GenerativeModel('models/gemini-1.5-pro-latest')
factual_brain_model = genai.GenerativeModel('models/gemini-1.5-flash')
ranking_brain_model = genai.GenerativeModel('models/gemini-1.5-flash')
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('models/gemini-1.5-flash')

# --- Pydantic Data Models (Centralized) ---
class ChatMessage(BaseModel):
    role: str
    content: str

class UserQuery(BaseModel):
    history: List[ChatMessage]
    applied_filters: Optional[dict] = Field(default=None)
    candidate_pool: Optional[List[dict]] = Field(default=None)
    booking_context: Optional[dict] = Field(default=None)
    session_id: Optional[str] = Field(default=None)
    user_id: Optional[str] = Field(default=None)

class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    OUT_OF_SCOPE = "out_of_scope"

class GatekeeperDecision(BaseModel):
    intent: ChatIntent

app = FastAPI()

# --- CORS configuration ---
origins = [
    "http://localhost:8080",
    "https://sg-smile-saver-git-feature-chatbot-login-wall-gsps-projects.vercel.app",
    "https://www.sg-jb-dental.com" # Example
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Session management helpers ---
def create_session(user_id: str = None, initial_context: dict = None) -> Optional[str]:
    from uuid import uuid4
    session_id = str(uuid4())
    context = initial_context or {}
    try:
        supabase.table("sessions").insert({"session_id": session_id, "context": context, "user_id": user_id}).execute()
        return session_id
    except Exception as e:
        logging.error(f"Error creating session: {e}")
        return None

def get_session(session_id: str) -> Optional[dict]:
    try:
        response = supabase.table("sessions").select("*").eq("session_id", session_id).single().execute()
        return response.data if response.data else None
    except Exception as e:
        logging.error(f"Error fetching session {session_id}: {e}")
        return None

def update_session(session_id: str, context: dict) -> bool:
    try:
        supabase.table("sessions").update({"context": context}).eq("session_id", session_id).execute()
        return True
    except Exception as e:
        logging.error(f"Error updating session {session_id}: {e}")
        return False

RESET_KEYWORDS = ["never mind", "start over", "reset", "restart"]

@app.get("/")
def read_root():
    return {"message": "API is running"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    # --- "LOGIN WALL" AND API LIMITER ---
    if not query.user_id:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in to use the chatbot.")

    try:
        # Step 1: Securely get the user's API call count using the database function
        response = supabase.rpc('get_user_api_calls', {'user_id_input': query.user_id}).execute()
        api_calls_left = response.data

        # Step 2: Check if the user exists and has calls remaining
        if api_calls_left is None:
            raise HTTPException(status_code=404, detail="User profile not found. Please try signing out and in again.")
        if api_calls_left <= 0:
            raise HTTPException(status_code=429, detail="You have reached your monthly limit of API calls.")

        # Step 3: If checks pass, decrement the counter
        new_count = api_calls_left - 1
        supabase.table("user_profiles").update({"api_calls_remaining": new_count}).eq("id", query.user_id).execute()
        
        print(f"User {query.user_id} has {new_count} API calls remaining.")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"Error in API limiter for user {query.user_id}: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while verifying your access.")

    # --- Session Management ---
    session_id = query.session_id
    context = {}
    if session_id:
        session = get_session(session_id)
        if session and session.get("user_id") == query.user_id:
            context = session.get("context", {})
        else:
            session_id = create_session(user_id=query.user_id)
            context = {}
    else:
        session_id = create_session(user_id=query.user_id)
        context = {}

    if not query.history:
        return {"response": "Error: History is empty.", "session_id": session_id}

    # --- State Management ---
    latest_user_message = query.history[-1].content.lower()
    previous_filters = query.applied_filters or {}
    candidate_clinics = query.candidate_pool or []
    booking_context = query.booking_context or {}
    conversation_history_for_prompt = "\n".join([f"{msg.role}: {msg.content}" for msg in query.history])
    
    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")
    
    # --- Gatekeeper ---
    intent = ChatIntent.OUT_OF_SCOPE # Default to a safe, cheap intent
    try:
        # A simpler prompt for better reliability
        gatekeeper_prompt = f"""
        Analyze the most recent user message and classify the user's intent.
        
        Conversation History:
        {conversation_history_for_prompt}

        User's MOST RECENT message is: "{latest_user_message}"
        """
        gatekeeper_response = gatekeeper_model.generate_content(gatekeeper_prompt, tools=[GatekeeperDecision])
        part = gatekeeper_response.candidates[0].content.parts[0]
        if hasattr(part, 'function_call') and part.function_call.args:
            intent = part.function_call.args['intent']
            print(f"Gatekeeper decided intent is: {intent}")
        else:
            print(f"Gatekeeper Error: No valid function call. Defaulting to OUT_OF_SCOPE.")
    except Exception as e:
        print(f"Gatekeeper Exception: {e}. Defaulting to OUT_OF_SCOPE.")

    # --- Router ---
    response_data = {}
    if intent == ChatIntent.FIND_CLINIC:
        response_data = handle_find_clinic(
            latest_user_message=latest_user_message,
            conversation_history=conversation_history_for_prompt,
            previous_filters=previous_filters,
            candidate_clinics=candidate_clinics,
            factual_brain_model=factual_brain_model,
            ranking_brain_model=ranking_brain_model,
            embedding_model=embedding_model,
            generation_model=generation_model,
            supabase=supabase,
            RESET_KEYWORDS=RESET_KEYWORDS
        )
    elif intent == ChatIntent.BOOK_APPOINTMENT:
        response_data = handle_booking_flow(
            latest_user_message=latest_user_message,
            booking_context=booking_context,
            previous_filters=previous_filters,
            candidate_clinics=candidate_clinics,
            factual_brain_model=factual_brain_model
        )
    elif intent == ChatIntent.GENERAL_DENTAL_QUESTION:
        response_data = handle_qna(
            latest_user_message=latest_user_message,
            generation_model=generation_model
        )
    elif intent == ChatIntent.OUT_OF_SCOPE:
        response_data = handle_out_of_scope(latest_user_message)
    else:
        response_data = {"response": "I'm sorry, I'm not sure how to handle that."}

    # Pass through context state for all flows
    response_data["applied_filters"] = response_data.get("applied_filters", previous_filters)
    response_data["candidate_pool"] = response_data.get("candidate_pool", candidate_clinics)
    response_data["booking_context"] = response_data.get("booking_context", booking_context)

    # --- Final Response Assembly ---
    if not isinstance(response_data, dict):
        response_data = {"response": str(response_data)}
        
    update_session(session_id, context)
    response_data["session_id"] = session_id
    
    return response_data