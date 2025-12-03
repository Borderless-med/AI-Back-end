from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
import os
import logging
import re
from dotenv import load_dotenv
from uuid import uuid4
from enum import Enum
from typing import List, Optional
import jwt
from jwt import InvalidTokenError

# --- 1. SETUP & CONFIGURATION ---
load_dotenv()
COUNTRY_MEMORY_ENABLED = os.getenv("COUNTRY_MEMORY_ENABLED", "true").lower() in ("1","true","yes","on")
DEBUG_SMOKE = os.getenv("DEBUG_SMOKE", "false").lower() in ("1", "true", "yes", "on")

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

app = FastAPI()

# --- 2. IMPORTS (Brains & Flows) ---
# We use the centralized brains from your service file
from src.services.gemini_service import (
    gatekeeper_model, 
    factual_brain_model, 
    ranking_brain_model, 
    generation_model, 
    embedding_model_name
)

from services.session_service import add_conversation_message
from flows.find_clinic_flow import handle_find_clinic
from flows.booking_flow import handle_booking_flow
from flows.qna_flow import handle_qna
from flows.travel_flow import handle_travel_query
from flows.outofscope_flow import handle_out_of_scope
from flows.remember_flow import handle_remember_session

# --- 3. DATA MODELS ---
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
    TRAVEL_FAQ = "travel_faq"
    OUT_OF_SCOPE = "out_of_scope"

# --- 4. MIDDLEWARE & CORS ---

# SECURITY: Validate JWT secret on startup - fail fast if misconfigured
JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("CRITICAL: SUPABASE_JWT_SECRET environment variable not set. Cannot start application.")
print(f"✅ JWT secret loaded successfully: {JWT_SECRET[:8]}...{JWT_SECRET[-4:]}", flush=True)

@app.options("/chat")
async def chat_options():
    return Response(status_code=200)

origins = [
    "http://localhost:8080",
    "http://localhost:5173",
    "https://sg-smile-saver.vercel.app",
    "https://www.sg-jb-dental.com",
    "https://www.orachope.org",
    "https://orachope.org",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https://.*vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-Authorization", "Content-Type"],
    expose_headers=["X-Request-Id", "X-API-Version"],
)

# --- 5. HELPER FUNCTIONS ---

# Location & Intent Helpers
LOCATION_REQUIRED_INTENTS = {
    ChatIntent.FIND_CLINIC.value,
    ChatIntent.BOOK_APPOINTMENT.value,
    "get_price", "opening_hours", "cost", "schedule"
}
SG_SYNONYMS = {"singapore","sg","s'g","sin","sing","lion city","little red dot","singapura","local","home","here","this island"}
JB_SYNONYMS = {"johor bahru","johor","jb","j.b.","bahru","malaysia side","across the border","causeway","second link"}
TOWNSHIP_COUNTRY_MAP = {
    "jurong": "sg", "jurong east": "sg", "jurong west": "sg", "bedok": "sg", "chinatown": "sg",
    "toa payoh": "sg", "ang mo kio": "sg", "yishun": "sg", "tampines": "sg", "pasir ris": "sg",
    "taman molek": "jb", "molek": "jb", "mount austin": "jb", "austin heights": "jb", "taman mount austin": "jb",
    "tebrau": "jb", "adda heights": "jb", "bukit indah": "jb", "permas jaya": "jb", "skudai": "jb",
    "taman sutera": "jb", "taman pelangi": "jb", "taman johor jaya": "jb", "taman damansara aliff": "jb",
}

def normalize_location_terms(text: str) -> str | None:
    if not text: return None
    t = text.lower()
    if any(x in t for x in ["both","all","compare singapore and jb","sg and jb","jb and sg"]): return "both"
    if any(s in t for s in SG_SYNONYMS): return "sg"
    if any(s in t for s in JB_SYNONYMS): return "jb"
    for key, country in TOWNSHIP_COUNTRY_MAP.items():
        if key in t: return country
    return None

def resolve_ordinal_reference(message: str, candidate_pool: list) -> dict | None:
    """Resolve ordinal references with compound pattern priority to handle 'second one' correctly."""
    import re
    if not candidate_pool:
        return None
    
    msg_lower = message.lower().strip()
    
    # PRIORITY 1: Compound patterns (two-word ordinals checked FIRST)
    # This prevents 'second one' from matching 'one' pattern prematurely
    compound_patterns = [
        (r'\bfirst\s+(clinic|one|option)\b', 0),
        (r'\bsecond\s+(clinic|one|option)\b', 1),
        (r'\bthird\s+(clinic|one|option)\b', 2),
        (r'\bfourth\s+(clinic|one|option)\b', 3),
        (r'\bfifth\s+(clinic|one|option)\b', 4),
    ]
    
    for pattern, index in compound_patterns:
        if re.search(pattern, msg_lower):
            if index < len(candidate_pool):
                print(f"[ORDINAL] Matched compound pattern '{pattern}' → index {index}")
                return candidate_pool[index]
    
    # PRIORITY 2: Simple ordinal patterns (checked SECOND)
    # Only reached if no compound pattern matched
    simple_patterns = [
        (r'\b(first|1st|#1)\b', 0),
        (r'\b(second|2nd|#2)\b', 1),
        (r'\b(third|3rd|#3)\b', 2),
        (r'\b(fourth|4th|#4)\b', 3),
        (r'\b(fifth|5th|#5)\b', 4),
    ]
    
    for pattern, index in simple_patterns:
        if re.search(pattern, msg_lower):
            if index < len(candidate_pool):
                print(f"[ORDINAL] Matched simple pattern '{pattern}' → index {index}")
                return candidate_pool[index]
    
    print(f"[ORDINAL] No ordinal pattern matched in: '{message}'")
    return None

def detect_booking_intent(message: str, candidate_pool: list) -> bool:
    """Detect if message contains booking signals + clinic reference."""
    msg_lower = message.lower()
    booking_verbs = ['book', 'schedule', 'appointment', 'reserve', 'arrange', 'set up']
    has_booking_verb = any(verb in msg_lower for verb in booking_verbs)
    if not has_booking_verb:
        return False
    # Check if clinic name or ordinal reference present
    if candidate_pool and any(c.get('name','').lower() in msg_lower for c in candidate_pool):
        return True
    # Check ordinal patterns
    if resolve_ordinal_reference(message, candidate_pool):
        return True
    # Check generic service + booking combo
    service_words = ['scaling', 'cleaning', 'root canal', 'implant', 'whitening', 'crown', 'filling', 'braces', 'wisdom']
    has_service = any(s in msg_lower for s in service_words)
    return has_booking_verb and has_service

# Auth Helpers
def get_user_id_from_jwt(request: Request):
    if request.method == "OPTIONS": return
    
    # print("\n--- ENTERING JWT VALIDATION ---", flush=True)
    auth_header = request.headers.get('X-authorization')
    # print(f"[JWT DEBUG] Auth header found: {auth_header is not None}", flush=True)

    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    
    token = auth_header.split(' ')[1]
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        user_id = payload.get('sub')
        if not user_id:
            raise HTTPException(status_code=401, detail="JWT missing 'sub' claim.")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Unexpected error: {e}")

# Session Helpers
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

def update_session(session_id: str, user_id: str, context: dict, conversation_history: list):
    try:
        supabase.table("sessions").update({
            "state": context,
            "context": conversation_history
        }).eq("session_id", session_id).eq("user_id", user_id).execute()
    except Exception as e:
        logging.error(f"Error updating session {session_id}: {e}")

# --- 6. ENDPOINTS ---

@app.get("/")
def read_root():
    return {"message": "SG-JB Dental Chatbot API is running"}

@app.get("/health")
def health():
    return {"status": "ok", "version": os.getenv("RELEASE", "local"), "environment": os.getenv("ENVIRONMENT", "dev")}

@app.post("/restore_session")
async def restore_session(request: Request, query: SessionRestoreQuery):
    """
    Restore session state from database.
    Requires valid JWT token in X-Authorization header.
    """
    # SECURITY: No fallback authentication - JWT required
    user_id = get_user_id_from_jwt(request)
    
    session = get_session(query.session_id, user_id)
    if session:
        state = session.get("state") or {}
        context = session.get("context") or []
        
        # Return structured response with all key session data
        return {
            "success": True,
            "state": state,
            "applied_filters": state.get("applied_filters", {}),
            "candidate_pool": state.get("candidate_pool", []),
            "booking_context": state.get("booking_context", {}),
            "location_preference": state.get("location_preference"),
            "conversation_history": context[-6:] if context else []  # Last 3 turns
        }
    else:
        # NOTE: Returning 404 here is correct if session missing, frontend handles logic
        raise HTTPException(status_code=404, detail="Session not found.")

@app.post("/chat")
async def handle_chat(request: Request, query: UserQuery, response: Response):
    trace_id = str(uuid4())
    print(f"\n--- [trace:{trace_id}] NEW /CHAT REQUEST RECEIVED ---", flush=True)
    
    # 1. AUTHENTICATION
    try:
        secure_user_id = get_user_id_from_jwt(request)
    except HTTPException as e:
        print(f"[trace:{trace_id}] [ERROR] Auth failed: {e.detail}")
        raise e

    # 2. SESSION LOADING
    session_id = query.session_id
    session = get_session(session_id, secure_user_id) if session_id else None
    if not session:
        session_id = create_session(secure_user_id)
        if not session_id: raise HTTPException(status_code=500, detail="Could not create a new session.")
        state = {}
    else:
        state = session.get("state") or {}

    if not query.history: return {"response": "Error: History is empty.", "session_id": session_id}

    conversation_history = query.history
    latest_user_message = conversation_history[-1].content
    lower_msg = latest_user_message.lower()

    # Frontend sometimes reuses an old session_id but sends a brand new history
    # (only the latest user turn). Treat that as authoritative signal to drop
    # any persisted filters so we surface the location prompt again.
    is_frontend_fresh_start = len(conversation_history) == 1 and conversation_history[0].role == "user"
    if is_frontend_fresh_start:
        if state.get("location_preference") or state.get("applied_filters") or state.get("candidate_pool"):
            print(f"[trace:{trace_id}] [INFO] Frontend provided fresh history - clearing stale session state.")
        state["applied_filters"] = {}
        state["candidate_pool"] = []
        state["location_preference"] = None
        state.pop("service_pending", None)
        state.pop("has_searched_clinics", None)
        state.pop("last_candidate_pool", None)

    previous_filters = state.get("applied_filters", {})
    candidate_clinics = state.get("candidate_pool", [])
    booking_context = state.get("booking_context", {})

    # Log User Message
    try:
        add_conversation_message(supabase, secure_user_id, "user", latest_user_message)
    except Exception as e:
        logging.error(f"Failed to log user message: {e}")

    # 3. GLOBAL RESET CHECK
    reset_triggers = ["reset", "reset:", "reset -", "reset please", "start over", "restart", "new search"]
    if any(lower_msg.startswith(rt) for rt in reset_triggers):
        print(f"[trace:{trace_id}] [INFO] Global reset requested.")
        state["applied_filters"] = {}
        state["candidate_pool"] = []
        state["booking_context"] = {}
        state["location_preference"] = None
        state["awaiting_location"] = True
        state["hard_reset_active"] = True
        response_data = {
            "response": "Let me restart your search — which country would you like to explore?",
            "meta": {"type": "location_prompt", "options": [{"key": "jb", "label": "JB"}, {"key": "sg", "label": "SG"}, {"key": "both", "label": "Both"}]},
            "applied_filters": {}, "candidate_pool": [], "booking_context": {}
        }
        updated_history = [msg.dict() for msg in query.history]
        updated_history.append({"role": "assistant", "content": response_data["response"]})
        update_session(session_id, secure_user_id, state, updated_history)
        response_data["session_id"] = session_id
        return response_data

    # 4. GLOBAL LOCATION PREPROCESSING
    # If awaiting location and user sends a pure location term, capture it before routing
    if state.get("awaiting_location"):
        inferred_location = normalize_location_terms(latest_user_message)
        if inferred_location:
            state["location_preference"] = inferred_location
            state.pop("awaiting_location", None)
            print(f"[trace:{trace_id}] [LOCATION] Captured: {inferred_location}")
            # Trigger a find clinic prompt to continue the flow
            response_data = {
                "response": f"Great! I'll search for clinics in {inferred_location.upper()}. What service are you looking for? (e.g., scaling, root canal, braces)",
                "applied_filters": {}, "candidate_pool": [], "booking_context": {}
            }
            updated_history = [msg.model_dump() for msg in query.history]
            updated_history.append({"role": "assistant", "content": response_data["response"]})
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data

    # --- 5. ROUTING LOGIC (RE-ORDERED WITH ENHANCEMENTS) ---
    intent = None
    gatekeeper_decision = None

    # A. Check for travel intent FIRST (Priority #1 - before ordinal)
    # If query has both ordinal reference AND travel keywords, it's a travel query
    travel_keywords = [
        "how to get", "get to", "directions", "route", "from singapore", "from sg",
        "to johor", "to jb", "causeway", "second link", "bus", "train", "ktm",
        "checkpoint", "immigration", "customs", "woodlands", "tuas", "shuttle", "cw",
        "transport", "travel", "commute", "prepare", "preparation", "mistakes", "common mistakes"
    ]
    has_travel_intent = any(k in lower_msg for k in travel_keywords)
    
    # V9 FIX 4: Check for educational queries BEFORE routing
    educational_patterns = [
        r"what is", r"what are", r"what's", r"whats", r"define", 
        r"tell me about", r"explain", r"can you explain", r"meaning of",
        r"what does .+ mean"
    ]
    is_educational = any(re.search(pattern, lower_msg, re.IGNORECASE) for pattern in educational_patterns)
    if is_educational:
        # Check if asking about a service/treatment (not a clinic or location)
        dental_terms = ["root canal", "scaling", "braces", "whitening", "implant", "filling", 
                       "extraction", "crown", "veneer", "cleaning", "checkup", "bonding",
                       "wisdom tooth", "orthodontic", "endodontic", "treatment"]
        is_about_treatment = any(term in lower_msg for term in dental_terms)
        # Exclude if they mention clinic names or locations
        has_clinic_or_location = any(term in lower_msg for term in ["clinic", "dentist", "singapore", "jb", "johor", "first", "second", "third"])
        if is_about_treatment and not has_clinic_or_location:
            print(f"[trace:{trace_id}] [V9 FIX] Educational query detected - routing to QnA: {latest_user_message}")
            intent = ChatIntent.GENERAL_DENTAL_QUESTION

    # Detect explicit location change requests ("show me JB instead", "switch to SG")
    location_change_triggers = ["show me", "switch to", "change to", "rather", "instead", "prefer"]
    location_change_target = normalize_location_terms(latest_user_message)
    has_location_change_intent = location_change_target and any(trigger in lower_msg for trigger in location_change_triggers)
    has_active_search_context = bool(candidate_clinics or previous_filters or state.get("last_candidate_pool"))

    if has_location_change_intent and has_active_search_context:
        print(f"[trace:{trace_id}] [INFO] Detected explicit location change request → {location_change_target.upper()}.")
        state["location_preference"] = location_change_target
        state["awaiting_location"] = False
        state["candidate_pool"] = []  # force fresh search for new geography
        candidate_clinics = []
        if isinstance(previous_filters, dict):
            updated_filters = dict(previous_filters)
            if location_change_target == "sg":
                updated_filters["country"] = "SG"
            elif location_change_target == "jb":
                updated_filters["country"] = "MY"
            else:
                updated_filters.pop("country", None)
            state["applied_filters"] = updated_filters
            previous_filters = updated_filters
        has_travel_intent = False  # override travel heuristic so we do not enter FAQ flow
        intent = ChatIntent.FIND_CLINIC
    
    # B. Check for ordinal references to existing clinics (Priority #2)
    # But skip if this is primarily a travel query
    ordinal_pattern = r'\b(first|second|third|1st|2nd|3rd|#1|#2|#3)\b.*(clinic|one|option|list)'
    if re.search(ordinal_pattern, lower_msg, re.IGNORECASE) and not has_travel_intent:
        # V8 FIX: Check for booking keywords FIRST to prevent ordinal hijacking
        booking_keywords = ["book", "appointment", "schedule", "reserve", "make an appointment", "i want to book"]
        has_booking_intent = any(kw in lower_msg for kw in booking_keywords)
        
        if has_booking_intent:
            print(f"[trace:{trace_id}] [V8 FIX] Booking keyword detected - skipping ordinal check")
            intent = ChatIntent.BOOK_APPOINTMENT
        elif not candidate_clinics:
            print(f"[trace:{trace_id}] [ORDINAL] Pattern detected but no candidates available.")
            state["awaiting_location"] = True
            response_data = {
                "response": "I don't have a clinic list ready right now. Let me help you search — which country would you like to explore?",
                "applied_filters": {}, "candidate_pool": [], "booking_context": {},
                "meta": {"type": "location_prompt", "options": [{"key": "jb", "label": "JB"}, {"key": "sg", "label": "SG"}, {"key": "both", "label": "Both"}]}
            }
            updated_history = [msg.model_dump() for msg in query.history]
            updated_history.append({"role": "assistant", "content": response_data["response"]})
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data
        else:
            ordinal_clinic = resolve_ordinal_reference(latest_user_message, candidate_clinics)
            if ordinal_clinic:
                state["selected_clinic_id"] = ordinal_clinic.get("id")
                print(f"[trace:{trace_id}] [ORDINAL] Resolved to: {ordinal_clinic.get('name')}")
                # Store clinic name in booking context for later booking initiation
                updated_booking_context = booking_context.copy()
                updated_booking_context["selected_clinic_name"] = ordinal_clinic.get('name')
                response_data = {
                    "response": f"**{ordinal_clinic.get('name')}**\n\nAddress: {ordinal_clinic.get('address')}\nRating: {ordinal_clinic.get('rating')} ({ordinal_clinic.get('reviews')} reviews)\nHours: {ordinal_clinic.get('operating_hours', 'N/A')}\n\nWould you like to book an appointment here, or get travel directions?",
                    "applied_filters": previous_filters,
                    "candidate_pool": candidate_clinics,
                    "booking_context": updated_booking_context,
                    "meta": {"type": "clinic_detail", "clinic": ordinal_clinic}
                }
                updated_history = [msg.model_dump() for msg in query.history]
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                update_session(session_id, secure_user_id, state, updated_history)
                response_data["session_id"] = session_id
                return response_data
            else:
                # Pattern matched but couldn't resolve - return first clinic as fallback
                print(f"[trace:{trace_id}] [ORDINAL] Pattern matched but resolve failed - returning first clinic.")
                first_clinic = candidate_clinics[0]
                state["selected_clinic_id"] = first_clinic.get("id")
                response_data = {
                    "response": f"**{first_clinic.get('name')}**\n\nAddress: {first_clinic.get('address')}\nRating: {first_clinic.get('rating')} ({first_clinic.get('reviews')} reviews)\nHours: {first_clinic.get('operating_hours', 'N/A')}\n\nWould you like to book an appointment here, or get travel directions?",
                    "applied_filters": previous_filters,
                    "candidate_pool": candidate_clinics,
                    "booking_context": booking_context,
                    "meta": {"type": "clinic_detail", "clinic": first_clinic}
                }
                updated_history = [msg.model_dump() for msg in query.history]
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                update_session(session_id, secure_user_id, state, updated_history)
                response_data["session_id"] = session_id
                return response_data

    # C. Check for booking intent (Priority #3)
    # Early booking detection to prevent travel FAQ hijacking
    booking_keywords = ["book", "appointment", "schedule", "reserve", "confirm", "booking"]
    has_booking_intent = any(kw in lower_msg for kw in booking_keywords)
    has_booking_context = bool(candidate_clinics or booking_context.get("status"))
    
    # If user is in active booking flow, check for exit keywords FIRST
    if booking_context.get("status") in ["confirming_details", "gathering_info"]:
        # Check if user wants to cancel/exit booking
        cancel_keywords = ["cancel", "stop", "quit", "exit", "no", "nope", "don't want", "do not want"]
        travel_keywords = ["direction", "travel", "get there", "how to go", "how do i get"]
        
        has_cancel_intent = any(kw in lower_msg for kw in cancel_keywords)
        has_travel_intent_in_booking = any(kw in lower_msg for kw in travel_keywords)
        
        if has_cancel_intent and not has_booking_intent:
            print(f"[trace:{trace_id}] [BOOKING] User wants to cancel - clearing booking context.")
            intent = ChatIntent.CANCEL_BOOKING
        elif has_travel_intent_in_booking:
            print(f"[trace:{trace_id}] [BOOKING] User asking for travel directions - routing to travel FAQ.")
            intent = ChatIntent.TRAVEL_FAQ
        else:
            print(f"[trace:{trace_id}] [BOOKING] Active booking flow detected - continuing booking.")
            intent = ChatIntent.BOOK_APPOINTMENT
    elif has_booking_intent and has_booking_context:
        print(f"[trace:{trace_id}] [BOOKING] Early booking detection - overriding travel/semantic checks.")
        intent = ChatIntent.BOOK_APPOINTMENT
    elif detect_booking_intent(latest_user_message, candidate_clinics):
        intent = ChatIntent.BOOK_APPOINTMENT
        print(f"[trace:{trace_id}] [BOOKING] Detected booking intent via signals.")

    # D. Check if currently booking (Priority #4)
    if intent is None:
        if booking_context.get('status') == 'confirming_details':
            user_reply = latest_user_message.strip().lower()
            if any(x in user_reply for x in ['yes', 'yep', 'yeah', 'ya', 'ok', 'confirm', 'correct', 'proceed']):
                intent = ChatIntent.BOOK_APPOINTMENT
            elif any(x in user_reply for x in ['no', 'nope', 'cancel', 'stop', 'wait', 'wrong clinic']):
                intent = ChatIntent.CANCEL_BOOKING
        elif booking_context.get('status') == 'gathering_info':
            intent = ChatIntent.BOOK_APPOINTMENT
    
    # E. Gatekeeper (Priority #5 - decision-maker when not clear from heuristics)
    # Skip gatekeeper if we already determined intent (saves 5-8 seconds)
    if intent is None:
        # Only run gatekeeper for truly ambiguous queries
        should_run_gatekeeper = not (has_travel_intent or has_booking_intent or has_location_change_intent)
        
        if should_run_gatekeeper:
            try:
                gate_prompt = f"""
                You are an intent gatekeeper. Classify the user's latest message into one of:
                FIND_CLINIC, BOOK_APPOINTMENT, CANCEL_BOOKING, GENERAL_DENTAL_QUESTION, REMEMBER_SESSION, TRAVEL_FAQ, OUT_OF_SCOPE.
                Return JSON: {{"intent": "...", "confidence": 0.0}}
                History:
                {query.history}
                Latest: "{latest_user_message}"
                """
                resp = gatekeeper_model.generate_content(gate_prompt)
                text = (resp.text or "").strip()
                import json as _json
                parsed = _json.loads(text) if text.startswith("{") else {}
                gate_intent = parsed.get("intent")
                gate_conf = float(parsed.get("confidence", 0))
                gatekeeper_decision = {"intent": gate_intent, "confidence": gate_conf}
                print(f"[trace:{trace_id}] [Gatekeeper] intent={gate_intent} conf={gate_conf:.2f}")
                # Accept gatekeeper decision only if high confidence
                if gate_intent in [i.value for i in ChatIntent] and gate_conf >= 0.7:
                    intent = ChatIntent(gate_intent)
            except Exception as e:
                print(f"[trace:{trace_id}] [Gatekeeper] error: {e}")
        else:
            print(f"[trace:{trace_id}] [Gatekeeper] Skipped - intent already determined by heuristics.")

    # F. Intent Heuristics (Safety Net - Priority #6)
    if intent is None:
        # 1) Travel override: clear travel phrasing (before QnA) - reuse travel_keywords from above
        if has_travel_intent:
            intent = ChatIntent.TRAVEL_FAQ
        # 2) Remember session check (NEW - BEFORE QnA and search triggers)
        # Must check BEFORE search triggers because "recommend" appears in both
        elif any(k in lower_msg for k in [
            "remind", "recall", "remember", 
            "what did", "what clinics", "which clinics",
            "previous", "earlier", "before", "last time",
            "you showed", "you recommended", "you suggested",
            "from before", "from earlier"
        ]):
            print(f"[trace:{trace_id}] [INFO] Heuristic detected Remember Session intent.")
            intent = ChatIntent.REMEMBER_SESSION
        # 3) QnA shortcut: educational questions take PRIORITY over service matching
        elif any(lower_msg.startswith(p) or f" {p}" in lower_msg for p in [
            "what is", "what are", "tell me about", "tell me more", "explain",
            "how does", "why is", "is it", "does", "should i", "can i",
            "how often", "how long", "when should", "how do you", "how do i"
        ]):
            intent = ChatIntent.GENERAL_DENTAL_QUESTION
        # 4) Dental find clinic heuristics (moved to position 4)
        else:
            search_triggers = ["find", "recommend", "suggest", "clinic", "dentist", "appointment", "nearby", "best"]
            service_triggers = ["scaling", "cleaning", "scale", "polish", "root canal", "implant", "whitening", "crown", "filling", "braces", "wisdom", "gum", "veneers"]
            has_search = any(k in lower_msg for k in search_triggers)
            has_service = any(k in lower_msg for k in service_triggers)
            if has_search or has_service:
                print(f"[trace:{trace_id}] [INFO] Heuristic detected Dental Intent (search={has_search}, service={has_service})")
                intent = ChatIntent.FIND_CLINIC

    # G. Semantic Travel FAQ Check (Priority #7)
    # V9 FIX 2: Don't hijack active booking flow with travel FAQ
    # Run if explicitly routed to TRAVEL_FAQ or if still no intent
    if intent == ChatIntent.TRAVEL_FAQ or (intent is None and has_travel_intent):
        # Guard: Don't hijack booking flow with travel FAQ
        if booking_context.get("status") in ["confirming_details", "awaiting_confirmation", "gathering_info"]:
            print(f"[trace:{trace_id}] [V9 GUARD] Booking flow active (status={booking_context.get('status')}) - skipping travel FAQ check, continuing with booking")
            intent = ChatIntent.BOOK_APPOINTMENT
        else:
            print(f"[trace:{trace_id}] [INFO] Engaging Semantic Travel FAQ check.")
            travel_resp = handle_travel_query(
                user_query=latest_user_message,
                supabase_client=supabase
            )

            if travel_resp:
                print(f"[trace:{trace_id}] [INFO] Semantic Travel FAQ found a strong match. Returning response.")
                response_data = travel_resp
                # Preserve candidate pool and filters
                response_data["applied_filters"] = response_data.get("applied_filters", previous_filters)
                response_data["candidate_pool"] = response_data.get("candidate_pool", candidate_clinics)
                response_data["booking_context"] = response_data.get("booking_context", booking_context)
                # --- Standard Response Saving ---
                updated_history = [msg.model_dump() for msg in query.history]
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                try:
                    add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
                except Exception as e:
                    logging.error(f"Failed to log assistant message: {e}")
                update_session(session_id, secure_user_id, state, updated_history)
                response_data["session_id"] = session_id
                return response_data

    # G. Fallback Intent
    if intent is None:
        intent = ChatIntent.GENERAL_DENTAL_QUESTION

    # --- 5. EXECUTION ---
    
    if intent == ChatIntent.FIND_CLINIC:
        # Reset check specific to flow
        if lower_msg.startswith("reset") or lower_msg.strip() in {"reset", "start over"}:
            state["applied_filters"] = {}
            state["candidate_pool"] = []
            state["booking_context"] = {}
            state["location_preference"] = None
            state["awaiting_location"] = True
            response_data = {
                "response": "Let me restart your search — which country would you like to explore?",
                "meta": {"type": "location_prompt", "options": [{"key": "jb", "label": "JB"}, {"key": "sg", "label": "SG"}, {"key": "both", "label": "Both"}]},
                "applied_filters": {}, "candidate_pool": [], "booking_context": {}
            }
            updated_history = [msg.model_dump() for msg in query.history]
            updated_history.append({"role": "assistant", "content": response_data["response"]})
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data

        # Location Logic with Conversation Progress Tracking
        location_pref = state.get("location_preference")
        service_pending = state.get("service_pending", False)
        
        # Conversation phase detection to prevent clearing location during refinement
        has_established_location = bool(state.get("location_preference"))
        is_empty_state = not candidate_clinics and not previous_filters
        is_multi_turn = len(conversation_history) > 2
        is_refining_search = has_established_location and is_empty_state and is_multi_turn
        is_awaiting_location = state.get("awaiting_location", False)
        
        if is_refining_search and not service_pending:
            # User is refining search (location already set, multi-turn conversation)
            # Example: "JB" → "dental scaling" → system asks for service again
            # PRESERVE location to avoid infinite loop
            print(f"[trace:{trace_id}] Refinement phase detected - preserving location: {location_pref}")
        elif is_frontend_fresh_start and is_empty_state:
            # True fresh start: frontend sent 1-message history
            print(f"[trace:{trace_id}] True fresh session - clearing persisted location preference.")
            location_pref = None
            state["location_preference"] = None
        elif service_pending:
            print(f"[trace:{trace_id}] Service pending - preserving location preference: {location_pref}")
        elif is_awaiting_location:
            print(f"[trace:{trace_id}] Awaiting location response - preserving location preference.")
        
        inferred = normalize_location_terms(latest_user_message)
        if inferred:
            state["location_preference"] = inferred
            location_pref = inferred
            state.pop("awaiting_location", None)
            # Clear service_pending when location is updated
            state.pop("service_pending", None)

        # Explicit Prompt for Location
        # Force location prompt if no location preference AND not waiting for location
        # This prevents defaulting to SG when user hasn't specified country
        if not location_pref and not state.get("awaiting_location", False):
            # Check if this is a dental search query (not ordinal/remember reference)
            requires_search = (
                not candidate_clinics or
                latest_user_message.lower() not in ["first", "second", "third", "first one", "second one", "third one"]
            )
            
            if requires_search:
                state["awaiting_location"] = True
                response_data = {
                    "response": "Which country would you like to explore?",
                    "meta": {"type": "location_prompt", "options": [{"key": "jb", "label": "JB"}, {"key": "sg", "label": "SG"}, {"key": "both", "label": "Both"}]},
                    "applied_filters": {}, "candidate_pool": [], "booking_context": {}
                }
                updated_history = [msg.model_dump() for msg in query.history]
                updated_history.append({"role": "assistant", "content": response_data["response"]})
                update_session(session_id, secure_user_id, state, updated_history)
                response_data["session_id"] = session_id
                return response_data

        # Execute Find Clinic
        effective_history = query.history
        if state.get("hard_reset_active"): effective_history = [query.history[-1]]

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
        # Preserve candidate pool and filters through QnA
        response_data["applied_filters"] = response_data.get("applied_filters", previous_filters)
        response_data["candidate_pool"] = response_data.get("candidate_pool", candidate_clinics)
        response_data["booking_context"] = response_data.get("booking_context", booking_context)

    elif intent == ChatIntent.REMEMBER_SESSION:
        response_data = handle_remember_session(session, latest_user_message)

    else: # Out of Scope
        response_data = handle_out_of_scope(latest_user_message)

    # --- 6. FINAL STATE SAVING ---
    
    if not isinstance(response_data, dict):
        response_data = {"response": str(response_data)}

    final_booking_context = response_data.get("booking_context", booking_context)
    flow_state_update = response_data.get("state_update", {}) or {}

    if final_booking_context.get("status") == "complete":
        new_state = {
            **state,  # Start with existing state to preserve all keys
            "applied_filters": previous_filters,
            "candidate_pool": candidate_clinics,
            "booking_context": {},
            **{k: v for k, v in flow_state_update.items()}
        }
    else:
        new_state = {
            **state,  # Start with existing state to preserve all keys
            "applied_filters": response_data.get("applied_filters", previous_filters),
            "candidate_pool": response_data.get("candidate_pool", candidate_clinics),
            "booking_context": final_booking_context,
            **{k: v for k, v in flow_state_update.items()}
        }

    if state.get("hard_reset_active"):
        new_state["hard_reset_active"] = False

    updated_history = [msg.model_dump() for msg in query.history]
    if response_data.get("response"):
        updated_history.append({"role": "assistant", "content": response_data["response"]})
        try:
            add_conversation_message(supabase, secure_user_id, "assistant", response_data["response"])
        except Exception as e:
            logging.error(f"Failed to log assistant message: {e}")

    update_session(session_id, secure_user_id, new_state, updated_history)
    response_data["session_id"] = session_id

    # Debug Meta
    if DEBUG_SMOKE:
        debug_payload = {
            "trace_id": trace_id,
            "intent": intent.value if intent else None,
            "final_applied_filters": new_state.get("applied_filters"),
            "candidate_count": len(new_state.get("candidate_pool", [])),
        }
        existing_meta = response_data.get("meta")
        if isinstance(existing_meta, dict):
            response_data["meta"] = {**existing_meta, "debug": debug_payload}
        else:
            response_data["meta"] = {"debug": debug_payload}

    response.headers["X-Request-Id"] = trace_id
    response.headers["X-API-Version"] = os.getenv("RELEASE", "local")

    return response_data