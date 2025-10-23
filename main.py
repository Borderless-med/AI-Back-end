# ==============================================================================
# Main FastAPI Application for the SG-JB Dental Chatbot
# ==============================================================================

import os
import logging
from dotenv import load_dotenv
from uuid import uuid4
from enum import Enum
from typing import List, Optional

# --- THIS IS THE FIX ---
# Load environment variables from the .env file immediately.
# This MUST be one of the very first things the application does,
# BEFORE any other local modules are imported that need these variables.
load_dotenv()

# --- Now we can safely import third-party libraries and our own modules ---
import jwt
from jwt import InvalidTokenError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client

# --- Import all models from our new, centralized Gemini Service ---
# This import can only happen AFTER load_dotenv() has run.
from src.services.gemini_service import (
    gatekeeper_model,
    factual_brain_model,
    ranking_brain_model,
    generation_model,
    embedding_model_name,
    booking_model,
    qna_model,
    outofscope_model,
    remember_model
)

# --- Import all of our separated flow handlers and helpers ---
from services.session_service import add_conversation_message
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.outofscope_flow import handle_out_of_scope
from flows.remember_flow import handle_remember_session

# --- Configure the Supabase client ---
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # Use the service_role key for admin actions
supabase: Client = create_client(supabase_url, supabase_key)

# --- Pydantic Data Models (API Request/Response Schemas) ---
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

class SessionRestoreQuery(BaseModel):
    session_id: str

class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    REMEMBER_SESSION = "remember_session"
    OUT_OF_SCOPE = "out_of_scope"

# --- FastAPI App Initialization and CORS Configuration ---
app = FastAPI()

origins = [
    "http://localhost:8080",
    "https://sg-smile-saver.vercel.app", # Production URL
    "https://www.sg-jb-dental.com",      # Custom Domain
    # Add your specific Vercel preview deployment URL for testing:
    "https://sg-smile-saver-git-feature-gemini-sdk-cleanup-gsps-projects.vercel.app" 
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions (Authentication & Session Management) ---
def get_user_id_from_jwt(request: Request):
    auth_header = request.headers.get('authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    
    token = auth_header.split(' ')[1]
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated"
        )
        user_id = payload.get('sub')
        if not user_id:
            raise HTTPException(status_code=401, detail="JWT missing 'sub' claim.")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

def create_session(user_id: str) -> Optional[str]:
    session_id = str(uuid4())
    try:
        supabase.table("sessions").insert({"session_id": session_id, "state": {}, "user_id": user_id}).execute()
        return session_id
    except Exception as e:
        logging.error(f"Error creating session: {e}")
        return None

def get_session(session_id: str, user_id: str) -> Optional[dict]:
    try:
        response = supabase.table("sessions").select("*").eq("session_id", session_id).eq("user_id", user_id).single().execute()
        return response.data if response.data else None
    except Exception as e:
        logging.error(f"Error fetching session {session_id} for user {user_id}: {e}")
        return None

def update_session(session_id: str, context: dict, conversation_history: list):
    try:
        supabase.table("sessions").update({
            "state": context,
            "context": conversation_history
        }).eq("session_id", session_id).execute()
    except Exception as e:
        logging.error(f"Error updating session {session_id}: {e}")

# --- API Endpoints ---
@app.get("/")
def read_root():
    return {"message": "SG-JB Dental Chatbot API is running"}

@app.post("/restore_session")
async def restore_session(request: Request, query: SessionRestoreQuery):
    user_id = get_user_id_from_jwt(request)
    session = get_session(query.session_id, user_id)
    if session:
        state = session.get("state") or {}
        return {"success": True, "state": state}
    else:
        raise HTTPException(status_code=404, detail="Session not found or access denied.")

@app.post("/chat")
async def handle_chat(request: Request, query: UserQuery):
    user_id = get_user_id_from_jwt(request)

    # --- Session Initialization ---
    session_id = query.session_id
    state = {}
    session = None
    if session_id:
        session = get_session(session_id, user_id)
    
    if session:
        state = session.get("state") or {}
    else:
        session_id = create_session(user_id)
        if not session_id:
            raise HTTPException(status_code=500, detail="Could not create a new session.")

    # --- Extract Latest Message and Context ---
    if not query.history:
        return {"response": "Error: History is empty.", "session_id": session_id}
    latest_user_message = query.history[-1].content
    previous_filters = state.get("applied_filters", {})
    candidate_clinics = state.get("candidate_pool", [])
    booking_context = state.get("booking_context", {})

    # --- Log User Message ---
    try:
        add_conversation_message(supabase, user_id, "user", latest_user_message)
    except Exception as e:
        logging.error(f"Failed to log user message: {e}")

    # --- Gatekeeper: Determine User Intent ---
    intent = ChatIntent.OUT_OF_SCOPE # Default intent
    try:
        gatekeeper_prompt = f"""
        Analyze the user's latest message and classify their intent.
        User message: "{latest_user_message}"
        Possible intents are: find_clinic, book_appointment, general_dental_question, remember_session, out_of_scope.
        Respond with ONLY one of the possible intents, and nothing else.
        """
        response = gatekeeper_model.generate_content(gatekeeper_prompt)
        
        print(f"[DEBUG] Raw Gatekeeper Response Text: '{response.text}'")

        parsed_intent = response.text.strip().lower()
        if parsed_intent in [e.value for e in ChatIntent]:
            intent = ChatIntent(parsed_intent)
        else:
            print(f"[WARNING] Parsed intent '{parsed_intent}' not found in ChatIntent enum. Defaulting to OUT_OF_SCOPE.")
            intent = ChatIntent.OUT_OF_SCOPE

        print(f"[INFO] Gatekeeper FINAL classified intent as: {intent.value}")

    except Exception as e:
        print(f"[ERROR] Gatekeeper model failed: {e}. Defaulting to OUT_OF_SCOPE.")
        intent = ChatIntent.OUT_OF_SCOPE

    # --- Router: Route to the appropriate flow based on intent ---
    response_data = {}
    if intent == ChatIntent.FIND_CLINIC:
        response_data = handle_find_clinic(
            latest_user_message=latest_user_message,
            conversation_history=query.history,
            previous_filters=previous_filters,
            candidate_clinics=candidate_clinics,
            factual_brain_model=factual_brain_model,
            ranking_brain_model=ranking_brain_model,
            embedding_model=embedding_model_name,
            generation_model=generation_model,
            supabase=supabase,
            RESET_KEYWORDS=["reset", "start over"]
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
    elif intent == ChatIntent.REMEMBER_SESSION:
        response_data = handle_remember_session(
            session=session,
            latest_user_message=latest_user_message
        )
    elif intent == ChatIntent.OUT_OF_SCOPE:
        response_data = handle_out_of_scope(latest_user_message)
    else:
        response_data = {"response": "I'm sorry, I'm not sure how to handle that."}

    # --- Final Response Assembly and Session Update ---
    if not isinstance(response_data, dict):
        response_data = {"response": str(response_data)}

    new_state = {
        "applied_filters": response_data.get("applied_filters", previous_filters),
        "candidate_pool": response_data.get("candidate_pool", candidate_clinics),
        "booking_context": response_data.get("booking_context", booking_context)
    }
    
    updated_history = [msg.dict() for msg in query.history]
    if response_data.get("response"):
        updated_history.append({"role": "assistant", "content": response_data["response"]})
        try:
            add_conversation_message(supabase, user_id, "assistant", response_data["response"])
        except Exception as e:
            logging.error(f"Failed to log assistant message: {e}")

    update_session(session_id, new_state, updated_history)
    
    response_data["session_id"] = session_id

    return response_data