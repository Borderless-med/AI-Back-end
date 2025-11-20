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
COUNTRY_MEMORY_ENABLED = os.getenv("COUNTRY_MEMORY_ENABLED", "true").lower() in ("1","true","yes","on")

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
from flows.travel_flow import handle_travel_query, extract_keywords
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

# Township to country hints to infer SG/JB from area names in the same message
TOWNSHIP_COUNTRY_MAP = {
    # Singapore areas
    "jurong": "sg", "jurong east": "sg", "jurong west": "sg", "bedok": "sg", "chinatown": "sg",
    "toa payoh": "sg", "ang mo kio": "sg", "yishun": "sg", "tampines": "sg", "pasir ris": "sg",
    # Johor Bahru areas
    "taman molek": "jb", "molek": "jb", "mount austin": "jb", "austin heights": "jb", "taman mount austin": "jb",
    "tebrau": "jb", "adda heights": "jb", "bukit indah": "jb", "permas jaya": "jb", "skudai": "jb",
    "taman sutera": "jb", "taman pelangi": "jb", "taman johor jaya": "jb", "taman damansara aliff": "jb",
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
    # infer from known township/area names
    for key, country in TOWNSHIP_COUNTRY_MAP.items():
        if key in t:
            return country
    return None

origins = [
    "http://localhost:8080",
    "http://localhost:5173",
    "https://sg-smile-saver.vercel.app",
    "https://www.sg-jb-dental.com",
    # Production domain(s)
    "https://www.orachope.org",
    "https://orachope.org",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https://.*vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    # Explicitly include custom headers commonly used by the SPA
    allow_headers=["*", "X-Authorization", "Content-Type"],
    expose_headers=["X-Request-Id", "X-API-Version"],
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

# Lightweight health endpoint for smoke tests and uptime checks
@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": os.getenv("RELEASE", "local"),
        "environment": os.getenv("ENVIRONMENT", "dev")
    }

@app.post("/restore_session")
async def restore_session(request: Request, query: SessionRestoreQuery):
    user_id = get_user_id_from_jwt(request)
    session = get_session(query.session_id, user_id)
    if session:
        state = session.get("state") or {}
        return {"success": True, "state": state}
    else:
        raise HTTPException(status_code=404, detail="Session not found or access denied.")

DEBUG_SMOKE = os.getenv("DEBUG_SMOKE", "false").lower() in ("1", "true", "yes", "on")

@app.post("/chat")
async def handle_chat(request: Request, query: UserQuery, response: Response):
    trace_id = str(uuid4())
    print(f"\n--- [trace:{trace_id}] NEW /CHAT REQUEST RECEIVED ---", flush=True)
    try:
        # REMARK: The variable is renamed to 'secure_user_id' for clarity. This is now the single source of truth.
        secure_user_id = get_user_id_from_jwt(request)
        print(f"[trace:{trace_id}] [INFO] JWT validation successful for user: {secure_user_id}", flush=True)
    except HTTPException as e:
        print(f"[trace:{trace_id}] [ERROR] Authentication failed with status {e.status_code}: {e.detail}", flush=True)
        raise e
    except Exception as e:
        print(f"[trace:{trace_id}] [FATAL ERROR] An unexpected error occurred in /chat endpoint: {e}", flush=True)
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
    lower_msg = latest_user_message.lower()

    try:
        add_conversation_message(supabase, secure_user_id, "user", latest_user_message)
    except Exception as e:
        logging.error(f"Failed to log user message: {e}")

    # --- Global RESET short-circuit (runs before intent classification) ---
    reset_triggers = [
        "reset", "reset:", "reset -", "reset please", "start over", "restart", "new search"
    ]
    if any(lower_msg.startswith(rt) for rt in reset_triggers):
        print(f"[trace:{trace_id}] [INFO] Global reset requested. Clearing session state and prompting for location.")
        state["applied_filters"] = {}
        state["candidate_pool"] = []
        state["booking_context"] = {}
        state["location_preference"] = None
        state["awaiting_location"] = True
        # Mark that a hard reset is in effect so the next turn won't reuse pre-reset history
        state["hard_reset_active"] = True
        response_data = {
            "response": "Let me restart your search — which country would you like to explore?",
            "meta": {"type": "location_prompt", "options": [
                {"key": "jb", "label": "Johor Bahru"},
                {"key": "sg", "label": "Singapore"},
                {"key": "both", "label": "Both"}
            ]},
            "applied_filters": {},
            "candidate_pool": [],
            "booking_context": {}
        }
        updated_history = [msg.dict() for msg in query.history]
        updated_history.append({"role": "assistant", "content": response_data["response"]})
        try:
            add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
        except Exception as e:
            logging.error(f"Failed to log assistant message: {e}")
        update_session(session_id, secure_user_id, state, updated_history)
        response_data["session_id"] = session_id
        return response_data

    # --- Router Logic ---
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
            gatekeeper_prompt = f"""Analyze the user's latest message and classify their intent.\nUser message: \"{latest_user_message}\"\nPossible intents are: find_clinic, book_appointment, general_dental_question, remember_session, out_of_scope.\nRespond with ONLY one of the possible intents, and nothing else."""
            gk_response = gatekeeper_model.generate_content(gatekeeper_prompt)
            print(f"[trace:{trace_id}] [DEBUG] Raw Gatekeeper Response Text: '{gk_response.text}'")
            parsed_intent = gk_response.text.strip().lower()
            if parsed_intent in [e.value for e in ChatIntent]:
                intent = ChatIntent(parsed_intent)
            else:
                intent = ChatIntent.OUT_OF_SCOPE
            print(f"[trace:{trace_id}] [INFO] Gatekeeper FINAL classified intent as: {intent.value}")
        except Exception as e:
            print(f"[trace:{trace_id}] [ERROR] Gatekeeper model failed: {e}. Defaulting to OUT_OF_SCOPE.")
            intent = ChatIntent.OUT_OF_SCOPE

    # --- Travel intent override ---
    travel_keywords = extract_keywords(latest_user_message)
    if (intent in {ChatIntent.OUT_OF_SCOPE, ChatIntent.GENERAL_DENTAL_QUESTION}) and travel_keywords:
        print(f"[trace:{trace_id}] [INFO] Travel keywords detected ({travel_keywords}); overriding intent to travel_faq.")
        travel_resp = handle_travel_query(latest_user_message, supabase, keyword_threshold=1)
        if travel_resp:
            response_data = travel_resp
            updated_history = [msg.dict() for msg in query.history]
            updated_history.append({"role": "assistant", "content": response_data["response"]})
            try:
                add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
            except Exception as e:
                logging.error(f"Failed to log assistant message: {e}")
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data

    # Override misclassifications: if message clearly asks to find/recommend clinics OR mentions a service, force FIND_CLINIC
    if intent in {ChatIntent.GENERAL_DENTAL_QUESTION, ChatIntent.OUT_OF_SCOPE}:
        search_triggers = ["find", "recommend", "suggest", "clinic", "dentist", "book", "appointment", "nearby"]
        service_triggers = [
            "cleaning","scale","scaling","polish","root canal","implant","whitening","crown",
            "filling","braces","wisdom tooth","gum treatment","veneers","tmj","sleep apnea"
        ]
        # Question-style openers: treat as informational unless explicit search verbs present
        question_starts = [
            "what ","what's","what is","how ","how's","how does","why ","does ","is ","are ","difference","explain","tell me about","tell me all about","what are"
        ]
        is_question_style = lower_msg.endswith("?") or any(lower_msg.startswith(q) for q in question_starts)
        has_search_trigger = any(k in lower_msg for k in search_triggers)
        has_service_trigger = any(k in lower_msg for k in service_triggers)
        # Only override if a search trigger exists OR a service trigger exists WITHOUT question style.
        if has_search_trigger or (has_service_trigger and not is_question_style):
            print(f"[trace:{trace_id}] [INFO] Heuristic override engaged (search={has_search_trigger}, service={has_service_trigger}, question_style={is_question_style}) -> FIND_CLINIC")
            intent = ChatIntent.FIND_CLINIC
        else:
            print(f"[trace:{trace_id}] [INFO] Retaining Q&A intent (question_style={is_question_style}, search={has_search_trigger}, service={has_service_trigger})")

    # Travel flow pre-check: conservative threshold (2 keywords)
    travel_resp = handle_travel_query(latest_user_message, supabase, keyword_threshold=2)
    if travel_resp:
        response_data = travel_resp
    else:
        response_data = {}
    if response_data:
        # travel flow already handled; skip other flows
        pass
    elif intent == ChatIntent.FIND_CLINIC:
        # Global RESET handling: if user requests reset, clear server state and force location prompt
        if lower_msg.startswith("reset") or lower_msg.strip() in {"reset", "start over"}:
            print(f"[trace:{trace_id}] [INFO] Reset requested. Clearing filters and forcing location prompt.")
            state["applied_filters"] = {}
            state["candidate_pool"] = []
            state["booking_context"] = {}
            state["location_preference"] = None
            state["awaiting_location"] = True
            response_data = {
                "response": "Let me restart your search — which country would you like to explore?",
                "meta": {"type": "location_prompt", "options": [
                    {"key": "jb", "label": "Johor Bahru"},
                    {"key": "sg", "label": "Singapore"},
                    {"key": "both", "label": "Both"}
                ]},
                # Do not echo any previous filters on a reset
                "applied_filters": {},
                "candidate_pool": [],
                "booking_context": {}
            }
            # Short-circuit on reset
            updated_history = [msg.dict() for msg in query.history]
            if response_data.get("response"):
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                try:
                    add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
                except Exception as e:
                    logging.error(f"Failed to log assistant message: {e}")
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data

        # LOCATION DECISION LAYER
        location_pref = state.get("location_preference")
        pending_location = state.get("awaiting_location", False)
        inferred = normalize_location_terms(latest_user_message)
        # If this looks like a fresh convo (first user turn) and no explicit location in text, ignore persisted location to avoid surprising auto-selection
        is_first_turn = len(query.history) == 1 and query.history[0].role == "user"
        if is_first_turn and not inferred:
            if location_pref:
                print(f"[trace:{trace_id}] [INFO] Fresh turn detected. Clearing persisted location_preference to prompt user explicitly.")
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
                # Keep a short text for accessibility; UI should render buttons from meta
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
            }
        else:
            # Mid-session explicit re-prompt: if user is searching and did not state SG/JB and no choose_location provided, prompt again
            search_triggers = ["find", "recommend", "suggest", "clinic", "dentist", "book", "appointment", "best"]
            choice = (query.booking_context or {}).get("choose_location") if isinstance(query.booking_context, dict) else None
            switch_phrases = ["switch", "change to", "show sg", "show jb", "switch to", "move to sg", "move to jb", "sg please", "jb please"]
            should_prompt = (
                location_pref and not inferred and any(k in lower_msg for k in search_triggers) and not choice
            )
            if COUNTRY_MEMORY_ENABLED:
                # Suppress re-prompt unless user explicitly indicates switch intent
                if any(p in lower_msg for p in switch_phrases):
                    print(f"[trace:{trace_id}] [INFO] Explicit location switch phrase detected; prompting for confirmation.")
                    state["awaiting_location"] = True
                else:
                    should_prompt = False
            if should_prompt:
                print(f"[trace:{trace_id}] [INFO] Mid-session search detected without explicit location; prompting for country selection again.")
                state["awaiting_location"] = True
                response_data = {
                    "response": "Which country would you like to explore?",
                    "meta": {"type": "location_prompt", "options": [
                        {"key": "jb", "label": "Johor Bahru"},
                        {"key": "sg", "label": "Singapore"},
                        {"key": "both", "label": "Both"}
                    ]},
                    "applied_filters": {},
                    "candidate_pool": [],
                    "booking_context": {},
                }
                updated_history = [msg.dict() for msg in query.history]
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                try:
                    add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
                except Exception as e:
                    logging.error(f"Failed to log assistant message: {e}")
                update_session(session_id, secure_user_id, state, updated_history)
                response_data["session_id"] = session_id
                return response_data
            # Accept explicit location choice passed via booking_context
            if query.booking_context and isinstance(query.booking_context, dict):
                choice = query.booking_context.get("choose_location")
                if choice in {"jb","sg","both"}:
                    state["location_preference"] = choice
                    state.pop("awaiting_location", None)
                    print(f"[trace:{trace_id}] [LOCATION] Received explicit choose_location: {choice}")
            # If awaiting_location is set, ignore any client-provided filters until a choice arrives
            if state.get("awaiting_location"):
                previous_filters = {}
                candidate_clinics = []
            # If a hard reset was just performed, trim the history to avoid leaking pre-reset intents (e.g., old services)
            effective_history = query.history
            if state.get("hard_reset_active"):
                print(f"[trace:{trace_id}] [RESET] Hard reset is active — trimming conversation history for extraction to the latest turn only.")
                effective_history = [query.history[-1]]  # Only the latest user message

            response_data = handle_find_clinic(
                latest_user_message,
                effective_history,
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

        # Once we've handled the first post-reset turn, clear the hard reset flag so normal history can resume
        if state.get("hard_reset_active"):
            new_state["hard_reset_active"] = False

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

    # Attach optional debug meta and response headers for smoke tests
    if DEBUG_SMOKE:
        debug_payload = {
            "trace_id": trace_id,
            "intent": intent.value if intent else None,
            "awaiting_location": new_state.get("awaiting_location"),
            "location_preference": new_state.get("location_preference"),
            "hard_reset_active": new_state.get("hard_reset_active"),
            "final_applied_filters": new_state.get("applied_filters"),
            "candidate_count": len(new_state.get("candidate_pool", [])),
        }
        existing_meta = response_data.get("meta")
        if isinstance(existing_meta, dict):
            response_data["meta"] = {**existing_meta, "debug": debug_payload}
        else:
            response_data["meta"] = {"debug": debug_payload}

    # Always expose request id and version in headers for correlation (CORS-exposed)
    response.headers["X-Request-Id"] = trace_id
    response.headers["X-API-Version"] = os.getenv("RELEASE", "local")

    return response_data