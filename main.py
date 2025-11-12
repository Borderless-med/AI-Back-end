from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
import os
import logging
from dotenv import load_dotenv
from uuid import uuid4
from enum import Enum
from typing import List, Optional
import jwt
from jwt import InvalidTokenError

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Instantiate FastAPI app
app = FastAPI()

# OPTIONS handler for /chat to fix CORS preflight
@app.options("/chat")
async def chat_options():
    return Response(status_code=200)

# Business logic imports (keep only these after initial setup)
from src.services.gemini_service import gatekeeper_model, factual_brain_model, ranking_brain_model, generation_model, embedding_model_name
from services.session_service import add_conversation_message
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.outofscope_flow import handle_out_of_scope
from flows.remember_flow import handle_remember_session

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
    CANCEL_BOOKING = "cancel_booking"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    REMEMBER_SESSION = "remember_session"
    OUT_OF_SCOPE = "out_of_scope"

# --- Location & intent configuration additions ---
LOCATION_REQUIRED_INTENTS = {
    ChatIntent.FIND_CLINIC.value,
    ChatIntent.BOOK_APPOINTMENT.value,
    "get_price",
    "opening_hours",
    "cost",
    "schedule"
}

SG_SYNONYMS = {
    "singapore","sg","s'g","sin","sing","lion city","little red dot","singapura","local","home","here","this island"
}
JB_SYNONYMS = {
    "johor bahru","johor","jb","j.b.","bahru","malaysia side","across the border","causeway","second link"
}

def normalize_location_terms(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    # both present explicitly
    if any(x in t for x in ["both","all","compare singapore and jb","sg and jb","jb and sg"]):
        return "both"
    if any(s in t for s in SG_SYNONYMS):
        return "sg"
    if any(s in t for s in JB_SYNONYMS):
        return "jb"
    return None

origins = [
    "http://localhost:8080",
    "https://sg-smile-saver.vercel.app",
    "https://www.sg-jb-dental.com",
    "https://sg-smile-saver-git-deploy-fix-gsps-projects.vercel.app",
    "https://sg-smile-saver-git-prototype-ui-gsps-projects-5403164b.vercel.app"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-authorization"],
)

def get_user_id_from_jwt(request: Request):
    if request.method == "OPTIONS":
        return
    
    print("\n--- ENTERING JWT VALIDATION ---", flush=True)
    auth_header = request.headers.get('X-authorization')
    print(f"[JWT DEBUG] Auth header found: {auth_header is not None}", flush=True)

    if not auth_header or not auth_header.startswith('Bearer '):
        print("[JWT ERROR] Header missing or invalid format.", flush=True)
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    
    token = auth_header.split(' ')[1]
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    
    print(f"[JWT DEBUG] SUPABASE_JWT_SECRET loaded: {jwt_secret is not None}. Starts with: {jwt_secret[:4] if jwt_secret else 'None'}", flush=True)
    
    try:
        print("[JWT DEBUG] Attempting to decode token...", flush=True)
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"], audience="authenticated")
        print("[JWT SUCCESS] Token decoded successfully.", flush=True)
        user_id = payload.get('sub')
        if not user_id:
            print("[JWT ERROR] 'sub' claim missing from token.", flush=True)
            raise HTTPException(status_code=401, detail="JWT missing 'sub' claim.")
        return user_id
    except jwt.ExpiredSignatureError as e:
        print(f"[JWT ERROR] Token expired: {e}", flush=True)
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError as e:
        print(f"[JWT ERROR] Invalid token: {e}", flush=True)
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        print(f"[JWT ERROR] An unexpected error occurred: {e}", flush=True)
        raise HTTPException(status_code=401, detail=f"Unexpected error: {e}")

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

# --- REMARK: THIS IS THE FIRST PART OF THE FIX ---
# The function signature is changed to accept 'user_id'.
def update_session(session_id: str, user_id: str, context: dict, conversation_history: list):
    try:
        # REMARK: The query is changed to include '.eq("user_id", user_id)'.
        # This makes the update command specific enough to succeed.
        supabase.table("sessions").update({
            "state": context,
            "context": conversation_history
        }).eq("session_id", session_id).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"Error updating session {session_id}: {e}")

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
    print("\n--- NEW /CHAT REQUEST RECEIVED ---", flush=True)
    try:
        # REMARK: The variable is renamed to 'secure_user_id' for clarity. This is now the single source of truth.
        secure_user_id = get_user_id_from_jwt(request)
        print(f"[INFO] JWT validation successful for user: {secure_user_id}", flush=True)
    except HTTPException as e:
        print(f"[ERROR] Authentication failed with status {e.status_code}: {e.detail}", flush=True)
        raise e
    except Exception as e:
        print(f"[FATAL ERROR] An unexpected error occurred in /chat endpoint: {e}", flush=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

    session_id = query.session_id
    # REMARK: 'secure_user_id' is now used for all session operations.
    session = get_session(session_id, secure_user_id) if session_id else None
    if not session:
        session_id = create_session(secure_user_id)
        if not session_id:
            raise HTTPException(status_code=500, detail="Could not create a new session.")
        state = {}
    else:
        state = session.get("state") or {}

    if not query.history:
        return {"response": "Error: History is empty.", "session_id": session_id}
    latest_user_message = query.history[-1].content
    previous_filters = state.get("applied_filters", {})
    candidate_clinics = state.get("candidate_pool", [])
    booking_context = state.get("booking_context", {})

    try:
        add_conversation_message(supabase, secure_user_id, "user", latest_user_message)
    except Exception as e:
        logging.error(f"Failed to log user message: {e}")

    # --- Router Logic (This section is unchanged as it was already correct) ---
    intent = None
    if booking_context.get('status') == 'confirming_details':
        user_reply = latest_user_message.strip().lower()
        affirmative_responses = ['yes', 'yep', 'yeah', 'ya', 'ok', 'confirm', 'correct', 'proceed', 'sounds good', 'do it', 'sure', 'alright']
        negative_responses = ['no', 'nope', 'cancel', 'stop', 'wait', 'wrong clinic', 'not right']
        if user_reply in affirmative_responses:
            intent = ChatIntent.BOOK_APPOINTMENT
        elif user_reply in negative_responses:
            intent = ChatIntent.CANCEL_BOOKING
            
    elif booking_context.get('status') == 'gathering_info':
        intent = ChatIntent.BOOK_APPOINTMENT

    if intent is None:
        try:
            gatekeeper_prompt = f"""Analyze the user's latest message and classify their intent.
            User message: "{latest_user_message}"
            Possible intents are: find_clinic, book_appointment, general_dental_question, remember_session, out_of_scope.
            Respond with ONLY one of the possible intents, and nothing else."""
            response = gatekeeper_model.generate_content(gatekeeper_prompt)
            print(f"[DEBUG] Raw Gatekeeper Response Text: '{response.text}'")
            parsed_intent = response.text.strip().lower()
            if parsed_intent in [e.value for e in ChatIntent]:
                intent = ChatIntent(parsed_intent)
            else:
                intent = ChatIntent.OUT_OF_SCOPE
            print(f"[INFO] Gatekeeper FINAL classified intent as: {intent.value}")
        except Exception as e:
            print(f"[ERROR] Gatekeeper model failed: {e}. Defaulting to OUT_OF_SCOPE.")
            intent = ChatIntent.OUT_OF_SCOPE

    # Override misclassifications: if message clearly asks to find/recommend clinics, force FIND_CLINIC
    if intent in {ChatIntent.GENERAL_DENTAL_QUESTION, ChatIntent.OUT_OF_SCOPE}:
        lower_msg = latest_user_message.lower()
        search_triggers = ["find", "recommend", "suggest", "clinic", "dentist", "book", "appointment"]
        if any(k in lower_msg for k in search_triggers):
            print("[INFO] Heuristic override: Detected strong search intent; forcing FIND_CLINIC")
            intent = ChatIntent.FIND_CLINIC

    response_data = {}
    if intent == ChatIntent.FIND_CLINIC:
        # LOCATION DECISION LAYER
        location_pref = state.get("location_preference")
        pending_location = state.get("awaiting_location", False)
        inferred = normalize_location_terms(latest_user_message)
        # If this looks like a fresh convo (first user turn) and no explicit location in text, ignore persisted location to avoid surprising auto-selection
        is_first_turn = len(query.history) == 1 and query.history[0].role == "user"
        if is_first_turn and not inferred:
            if location_pref:
                print("[INFO] Fresh turn detected. Clearing persisted location_preference to prompt user explicitly.")
            state.pop("location_preference", None)
            location_pref = None
        if inferred:
            state["location_preference"] = inferred
            location_pref = inferred
            state.pop("awaiting_location", None)

        # If intent requires location but none known, prompt.
        if (ChatIntent.FIND_CLINIC.value in LOCATION_REQUIRED_INTENTS) and not location_pref and not pending_location:
            state["awaiting_location"] = True
            response_data = {
                "response": "To tailor results: which country are you interested in?",
                "meta": {"type": "location_prompt", "options": [
                    {"key": "jb", "label": "Johor Bahru"},
                    {"key": "sg", "label": "Singapore"},
                    {"key": "both", "label": "Both"}
                ]},
                "applied_filters": previous_filters,
                "candidate_pool": [],
                "booking_context": {},
            }
        else:
            # Accept explicit location choice passed via booking_context
            if query.booking_context and isinstance(query.booking_context, dict):
                choice = query.booking_context.get("choose_location")
                if choice in {"jb","sg","both"}:
                    state["location_preference"] = choice
                    state.pop("awaiting_location", None)
            response_data = handle_find_clinic(
                latest_user_message,
                query.history,
                previous_filters,
                candidate_clinics,
                factual_brain_model,
                ranking_brain_model,
                embedding_model_name,
                generation_model,
                supabase,
                ["reset", "start over"],
                session_state=state
            )
    elif intent == ChatIntent.BOOK_APPOINTMENT:
        response_data = handle_booking_flow(latest_user_message, booking_context, previous_filters, candidate_clinics, factual_brain_model)
    elif intent == ChatIntent.CANCEL_BOOKING:
        response_data = {"response": "Okay, I've cancelled that booking request. How else can I help you today?", "booking_context": {}}
    elif intent == ChatIntent.GENERAL_DENTAL_QUESTION:
        response_data = handle_qna(latest_user_message, generation_model)
    elif intent == ChatIntent.REMEMBER_SESSION:
        response_data = handle_remember_session(session, latest_user_message)
    else: # OUT_OF_SCOPE
        response_data = handle_out_of_scope(latest_user_message)

    if not isinstance(response_data, dict):
        response_data = {"response": str(response_data)}
        
    # --- REMARK: THIS IS THE SECOND PART OF THE FIX ---
    # This new block of logic intelligently decides what to save in the session state.
    final_booking_context = response_data.get("booking_context", booking_context)
    # pick up any state updates from flows (e.g., location_preference gate)
    flow_state_update = response_data.get("state_update", {}) or {}
    if final_booking_context.get("status") == "complete":
        # If booking is complete, preserve the recommendations for memory, but clear the active booking.
        new_state = {
            "applied_filters": previous_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": {},
            **{k: v for k, v in flow_state_update.items()}
        }
    else:
        # Otherwise, save the state as returned by the flow.
        new_state = {
            "applied_filters": response_data.get("applied_filters", previous_filters),
            "candidate_pool": response_data.get("candidate_pool", candidate_clinics),
            "booking_context": final_booking_context,
            **{k: v for k, v in flow_state_update.items()}
        }

    updated_history = [msg.dict() for msg in query.history]
    if response_data.get("response"):
        updated_history.append({"role": "assistant", "content": response_data["response"]})
        try:
            add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
        except Exception as e:
            logging.error(f"Failed to log assistant message: {e}")
            
    # REMARK: The call to update_session now correctly passes the 'secure_user_id'.
    update_session(session_id, secure_user_id, new_state, updated_history)
    
    response_data["session_id"] = session_id

    return response_data