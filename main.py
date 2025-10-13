"""
main.py - FastAPI backend entry point for SG-JB Dental Chatbot

Handles API routing, session management, and delegates to modular flow handlers (find clinic, booking, QNA, recall).
Persistent session, booking, and QNA flows are supported. User identification is via frontend user_id only.
"""


# Import helpers and models from new modules
from services.session_service import create_session, get_session, update_session, add_conversation_message
from models import ChatMessage, UserQuery, SessionRestoreQuery, ChatIntent, GatekeeperDecision

import sys
print(f"--- PYTHON VERSION CHECK --- : {sys.version}")
import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from supabase import create_client, Client
import logging


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
supabase_key = os.getenv("SUPABASE_KEY") # This MUST be your service_role key
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


app = FastAPI()

# --- CORS configuration ---
origins = [
    "http://localhost:8080", # For your local development
    "https://sg-smile-saver-git-feature-chatbot-login-wall-gsps-projects.vercel.app", # An old preview URL
    "https://sg-smile-saver-git-main-gsps-projects-5403164b.vercel.app", # An old production URL
    "https://sg-smile-saver-5rouwfubi-gsps-projects-5403164b.vercel.app", # The NEW URL from the error
    "https://sg-smile-saver.vercel.app", # Your clean production URL
    "https://www.sg-jb-dental.com" # Your final custom domain
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



RESET_KEYWORDS = ["never mind", "start over", "reset", "restart"]

@app.get("/")
def read_root():
    return {"message": "API is running"}

# --- NEW: Endpoint to restore session context ---
@app.post("/restore_session")
def restore_session(query: SessionRestoreQuery):
    print(f"Attempting to restore session {query.session_id} for user {query.user_id}")
    try:
        # Use user_id directly from frontend (no JWT)
        session = get_session(supabase, query.session_id, user_id=query.user_id)
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
        logging.error(f"Error restoring session {query.session_id} for user {query.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore session.")

@app.post("/chat")
def handle_chat(request: Request, query: UserQuery):
    # Use user_id directly from frontend (no JWT)
    user_id = query.user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in to use the chatbot.")

    try:
        # Step 1: Securely get the user's API call count using the database function
        response = supabase.rpc('get_user_api_calls', {'user_id_input': user_id}).execute()
        api_calls_left = response.data

        # Step 2: Check if the user exists and has calls remaining
        if api_calls_left is None:
            raise HTTPException(status_code=404, detail="User profile not found. Please try signing out and in again.")
        if api_calls_left <= 0:
            raise HTTPException(status_code=429, detail="You have reached your monthly limit of API calls.")

        # Step 3: If checks pass, call the database function to decrement the counter
        supabase.rpc('decrement_api_calls', {'user_id_input': user_id}).execute()

        print(f"User {user_id} has {api_calls_left - 1} API calls remaining.")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.error(f"Error in API limiter for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while verifying your access.")

    # --- Session Management ---
    session_id = query.session_id
    # Initialize standardized state structure
    state = {"applied_filters": {}, "candidate_pool": [], "booking_context": {}}
    
    if session_id:
        # Always use new get_session with user_id
        session = get_session(supabase, session_id, user_id=user_id)
        if not session:
            # REMARK: Session not found, create a new one for this user
            session_id = create_session(supabase, user_id=user_id)
            session = get_session(supabase, session_id, user_id=user_id)
        if session and session.get("user_id") == user_id:
            raw_state = session.get("state") or {}
            # Extract standardized state components
            state["applied_filters"] = raw_state.get("applied_filters") or {}
            state["candidate_pool"] = raw_state.get("candidate_pool") or []
            state["booking_context"] = raw_state.get("booking_context") or {}
        else:
            # REMARK: If still no session, handle as a critical error
            raise HTTPException(status_code=500, detail="Failed to create or fetch session.")
    else:
        session_id = create_session(supabase, user_id=user_id)
        session = get_session(supabase, session_id, user_id=user_id)
        if not session:
            raise HTTPException(status_code=500, detail="Failed to create or fetch session.")

    if not query.history:
        return {"response": "Error: History is empty.", "session_id": session_id}

    # --- State Management ---
    latest_user_message = query.history[-1].content.lower()
    previous_filters = state["applied_filters"]
    candidate_clinics = state["candidate_pool"]
    booking_context = state["booking_context"]
    conversation_history_for_prompt = "\n".join([f"{msg.role}: {msg.content}" for msg in query.history])
    
    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")
    
    # --- Gatekeeper ---
    intent = ChatIntent.OUT_OF_SCOPE # Default to a safe, cheap intent
    try:
        gatekeeper_prompt = f"""
        You are a highly intelligent and strict API routing assistant for a dental chatbot. 
        Your ONLY job is to analyze the user's most recent message and classify its intent into one of four categories.

        You MUST use the 'GatekeeperDecision' tool to provide your answer.

        Here are the definitions of the five intents:
        1.  'find_clinic': The user is asking to find, locate, or get recommendations for a dental clinic. This includes asking for a list, asking for the "best" clinic, or asking for clinics in a specific location.
        2.  'book_appointment': The user is explicitly asking to book, schedule, or make an appointment. This often follows a 'find_clinic' request.
        3.  'general_dental_question': The user is asking a general question about a dental procedure, concept, or pricing (e.g., "what is a root canal?", "how much are veneers?").
        4.  'remember_session': The user is asking the chatbot to recall, remember, or show information from previous conversations or sessions.
        5.  'out_of_scope': The user is having a casual conversation, greeting the chatbot, or asking a question completely unrelated to dentistry.

        --- EXAMPLES ---
        User Message: "Find me the best clinic for dental crown in JB"
        Intent: find_clinic

        User Message: "Okay, book me an appointment at Mount Austin Dental Hub"
        Intent: book_appointment

        User Message: "what is the price of teeth whitening?"
        Intent: general_dental_question

        User Message: "remeber the 3 clinics from last time"
        Intent: remember_session

        User Message: "do you remember what we talked about?"
        Intent: remember_session

        User Message: "can you recall our previous discussion?"
        Intent: remember_session

        User Message: "show me our last conversation"
        Intent: remember_session

        User Message: "what did we discuss in our past session?"
        Intent: remember_session

        User Message: "recollect what you told me before"
        Intent: remember_session

        User Message: "bring back our last interaction"
        Intent: remember_session

        User Message: "what was our previous chat about?"
        Intent: remember_session

        User Message: "hello, are you still there"
        Intent: out_of_scope
        ---

        Analyze the following conversation and determine the intent of the VERY LAST user message.

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
    elif intent == ChatIntent.REMEMBER_SESSION:
        # Fix: Get the session data properly, always use user_id
        session_data = get_session(supabase, session_id, user_id=query.user_id) if session_id else None
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
        # Add each user message to conversations table (enforce limit)
        add_conversation_message(user_id, msg.role, msg.content)

    # Add AI response to history
    if response_data.get("response"):
        conversation_history.append({"role": "assistant", "content": response_data["response"]})
        # Add assistant response to conversations table (enforce limit)
        add_conversation_message(user_id, "assistant", response_data["response"])

    update_session(session_id, new_state, conversation_history)
    response_data["session_id"] = session_id

    return response_data