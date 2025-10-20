import sys
print(f"--- PYTHON VERSION CHECK --- : {sys.version}")
import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import jwt
from jwt import InvalidTokenError
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional
import logging

def get_user_id_from_jwt(request: Request):
    print("[DEBUG] Entered get_user_id_from_jwt")
    auth_header = request.headers.get('authorization')
    print(f"[DEBUG] Authorization header: {auth_header}")
    if not auth_header or not auth_header.startswith('Bearer '):
        print("[ERROR] Missing or invalid Authorization header.")
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = auth_header.split(' ')[1]
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    print(f"[DEBUG] JWT secret loaded: {jwt_secret is not None}")
    try:
        print(f"[DEBUG] Attempting to decode JWT: {token[:30]}...")
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated"
        )
        print(f"[DEBUG] JWT decoded successfully: {payload}")
        user_id = payload.get('sub')
        if not user_id:
            print("[ERROR] JWT missing sub claim.")
            raise HTTPException(status_code=401, detail="JWT missing sub claim.")
        return user_id
    except jwt.ExpiredSignatureError:
        print("[ERROR] JWT verification failed: Token has expired.")
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError as e:
        print(f"[ERROR] JWT verification failed: Invalid token. Details: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error during JWT decoding: {e}")
        raise HTTPException(status_code=401, detail=f"Unexpected error: {e}")
# Import conversation logging helper
from services.session_service import add_conversation_message

# --- Import all five of our new, separated flow handlers ---
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.outofscope_flow import handle_out_of_scope
from flows.remember_flow import handle_remember_session

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # This MUST be your service_role key
supabase: Client = create_client(supabase_url, supabase_key)

# --- Define AI Models (Centralized) ---
# Use the most powerful and reliable model for the critical, multi-class Gatekeeper task.
gatekeeper_model = genai.GenerativeModel('gemini-pro-latest')

# Use the fast and cheap Flash model for the subsequent, simpler tasks.
factual_brain_model = genai.GenerativeModel('gemini-flash-latest')
ranking_brain_model = genai.GenerativeModel('gemini-flash-latest')

# The embedding model name is correct.
embedding_model = 'models/embedding-001' 

# Use the Flash model for the final, simple text generation.
generation_model = genai.GenerativeModel('gemini-flash-latest')

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

# --- NEW: Pydantic model for the session restore endpoint ---
class SessionRestoreQuery(BaseModel):
    session_id: str
    user_id: str

class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    REMEMBER_SESSION = "remember_session"
    OUT_OF_SCOPE = "out_of_scope"

class GatekeeperDecision(BaseModel):
    intent: ChatIntent

app = FastAPI()

# --- CORS configuration ---
origins = [
    "http://localhost:8080", # For your local development
    "https://sg-smile-saver-git-feature-chatbot-login-wall-gsps-projects.vercel.app", # An old preview URL
    "https://sg-smile-saver-git-main-gsps-projects-5403164b.vercel.app", # An old production URL
    "https://sg-smile-saver-5rouwfubi-gsps-projects-5403164b.vercel.app", # The NEW URL from the error
    "https://sg-smile-saver.vercel.app", # Your clean production URL
    "https://www.sg-jb-dental.com", # Your final custom domain
    "https://sg-smile-saver-git-jwt-migration-gsps-projects-5403164b.vercel.app" # CURRENT VERCEL DEPLOYMENT
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
    state = initial_context or {}
    try:
        supabase.table("sessions").insert({"session_id": session_id, "state": state, "user_id": user_id}).execute()
        return session_id
    except Exception as e:
        logging.error(f"Error creating session: {e}")
        return None
def get_session(session_id: str, user_id: str = None) -> Optional[dict]:
    try:
        query = supabase.table("sessions").select("*").eq("session_id", session_id)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.single().execute()
        return response.data if response.data else None

    except Exception as e:
        logging.error(f"Error fetching session {session_id} (user_id={user_id}): {e}")
        return None
            
def update_session(session_id: str, context: dict, conversation_history: list = None) -> bool:
    try:
        update_data = {"state": context}
        if conversation_history:
            update_data["context"] = conversation_history
        print(f"[DEBUG] Updating session {session_id} with data: {update_data}")
        result = supabase.table("sessions").update(update_data).eq("session_id", session_id).execute()
        print(f"[DEBUG] Supabase update result: {result}")
        return True
    except Exception as e:
        logging.error(f"Error updating session {session_id}: {e}")
        return False

RESET_KEYWORDS = ["never mind", "start over", "reset", "restart"]

@app.get("/")
def read_root():
    return {"message": "API is running"}

# --- NEW: Endpoint to restore session context ---
@app.post("/restore_session")
async def restore_session(request: Request, query: SessionRestoreQuery):
    print("[DEBUG] /restore_session endpoint called")
    print(f"[DEBUG] Request headers: {dict(request.headers)}")
    user_id = None
    try:
        user_id = get_user_id_from_jwt(request)
        print(f"[DEBUG] user_id from JWT: {user_id}")
    except Exception as e:
        print(f"[DEBUG] Exception in get_user_id_from_jwt: {e}")
        raise
    print(f"Attempting to restore session {query.session_id} for user {user_id}")
    try:
        session = get_session(query.session_id, user_id=user_id)
        if session:
            print("Session found and user verified. Returning context.")
            state = session.get("state") or {}
            return {"success": True, "state": {
                "applied_filters": state.get("applied_filters") or {},
                "candidate_pool": state.get("candidate_pool") or [],
                "booking_context": state.get("booking_context") or {}
            }}
        else:
            print("Session not found or user mismatch.")
            raise HTTPException(status_code=404, detail="Session not found or access denied.")
    except Exception as e:
        logging.error(f"Error restoring session {query.session_id} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore session.")


@app.post("/chat")
async def handle_chat(request: Request, query: UserQuery):
    print("[DEBUG] /chat endpoint called")
    user_id = get_user_id_from_jwt(request)
    print(f"[DEBUG] user_id from JWT: {user_id}")
    if not user_id:
        print("[ERROR] No user_id returned from JWT decode.")
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in to use the chatbot.")

    # --- API Limiter (optional, can be expanded) ---
    try:
        # Example: get API call count (can be expanded as needed)
        response = supabase.rpc('get_user_api_calls', {'user_id_input': user_id}).execute()
    except Exception as e:
        logging.error(f"Error in API limiter for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while verifying your access.")

    # --- Session Management ---
    session_id = query.session_id
    state = {"applied_filters": {}, "candidate_pool": [], "booking_context": {}}
    session = None
    if session_id:
        session = get_session(session_id, user_id=user_id)
        if session:
            # Use the existing session
            raw_state = session.get("state") or {}
            state["applied_filters"] = raw_state.get("applied_filters") or {}
            state["candidate_pool"] = raw_state.get("candidate_pool") or []
            state["booking_context"] = raw_state.get("booking_context") or {}
        else:
            # Provided session_id is missing or not owned by user, create new session
            session_id = create_session(user_id=user_id)
    else:
        # No session_id provided, create new session
        session_id = create_session(user_id=user_id)

    if not query.history:
        return {"response": "Error: History is empty.", "session_id": session_id}

    latest_user_message = query.history[-1].content.lower()
    previous_filters = state["applied_filters"]
    candidate_clinics = state["candidate_pool"]
    booking_context = state["booking_context"]

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")

    # Define conversation_history_for_prompt for downstream use
    conversation_history_for_prompt = query.history

    # Use gatekeeper_model to determine intent
    # --- Log user message to conversations table ---
    try:
        add_conversation_message(supabase, query.user_id, "user", query.history[-1].content)
    except Exception as e:
        logging.error(f"Failed to log user message to conversations: {e}")
    
    # --- Gatekeeper ---
    intent = ChatIntent.OUT_OF_SCOPE # Default to a safe, cheap intent
    try:
        try:
            gatekeeper_response = gatekeeper_model.generate_content(
                [{"role": "user", "parts": [latest_user_message]}],
                tools=[
                    {
                        "name": "classify_intent",
                        "description": "Classifies the user's intent for dental chatbot routing.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "intent": {
                                    "type": "string",
                                    "enum": [
                                        "find_clinic",
                                        "book_appointment",
                                        "general_dental_question",
                                        "remember_session",
                                        "out_of_scope"
                                    ],
                                    "description": "The classified intent of the user's query."
                                }
                            },
                            "required": ["intent"]
                        }
                    }
                ]
            )
            print(f"[DEBUG] Raw gatekeeper_response: {gatekeeper_response}")
            print(f"[DEBUG] gatekeeper_response type: {type(gatekeeper_response)}")
            # Do not parse anything yet, just print and raise to see the log
            raise Exception("DEBUG_BREAK_AFTER_RAW_GATEKEEPER_RESPONSE")
        except Exception as api_exc:
            print(f"[DEBUG] Gemini API call exception: {api_exc}")
            print(f"[DEBUG] Gemini API call exception type: {type(api_exc)}")
            raise
    except Exception as e:
        print(f"Gatekeeper Exception: {e}. Defaulting to OUT_OF_SCOPE.")
        intent = ChatIntent.OUT_OF_SCOPE

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
    elif intent == ChatIntent.REMEMBER_SESSION:
        # Fix: Get the session data properly instead of relying on variable scope
        session_data = get_session(session_id) if session_id else None
        response_data = handle_remember_session(
            session=session_data,
            latest_user_message=latest_user_message
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
    # Build new standardized state to persist
    new_state = {
        "applied_filters": response_data.get("applied_filters", previous_filters),
        "candidate_pool": response_data.get("candidate_pool", candidate_clinics),
        "booking_context": response_data.get("booking_context", booking_context)
    }
    
    if not isinstance(response_data, dict):
        response_data = {"response": str(response_data)}
    
    # Build conversation history for persistence
    conversation_history = []
    for msg in query.history:
        conversation_history.append({"role": msg.role, "content": msg.content})

    # Add AI response to history and log to conversations table
    if response_data.get("response"):
        conversation_history.append({"role": "assistant", "content": response_data["response"]})
        try:
            add_conversation_message(supabase, query.user_id, "assistant", response_data["response"])
        except Exception as e:
            logging.error(f"Failed to log assistant message to conversations: {e}")

    update_session(session_id, new_state, conversation_history)
    response_data["session_id"] = session_id

    return response_data