import logging
from typing import Optional
from supabase import Client

def create_session(supabase: Client, user_id: str = None, initial_context: dict = None) -> Optional[str]:
    from uuid import uuid4
    session_id = str(uuid4())
    state = initial_context or {}
    try:
        supabase.table("sessions").insert({"session_id": session_id, "state": state, "user_id": user_id}).execute()
        return session_id
    except Exception as e:
        logging.error(f"Error creating session: {e}")
        return None

def get_session(supabase: Client, session_id: str, user_id: str = None) -> Optional[dict]:
    try:
        query = supabase.table("sessions").select("*").eq("session_id", session_id)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.single().execute()
        return response.data if response.data else None
    except Exception as e:
        logging.error(f"Error fetching session {session_id} (user_id={user_id}): {e}")
        return None

def update_session(supabase: Client, session_id: str, context: dict, conversation_history: list = None) -> bool:
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

def add_conversation_message(supabase: Client, user_id, role, message, MESSAGE_LIMIT_PER_USER=100):
    try:
        count_resp = supabase.table("conversations").select("id,created_at").eq("user_id", user_id).order("created_at").execute()
        messages = count_resp.data or []
        if len(messages) >= MESSAGE_LIMIT_PER_USER:
            old_ids = [row["id"] for row in messages[:len(messages) - MESSAGE_LIMIT_PER_USER + 1]]
            if old_ids:
                supabase.table("conversations").delete().in_("id", old_ids).execute()
        supabase.table("conversations").insert({
            "user_id": user_id,
            "role": role,
            "message": message
        }).execute()
    except Exception as e:
        logging.error(f"Error inserting conversation message: {e}")

# NEW: Helper to get the most recent previous session for a user (excluding the current session)
def get_previous_session(supabase: Client, user_id: str, exclude_session_id: str):
    try:
        result = supabase.table("sessions") \
            .select("*") \
            .eq("user_id", user_id) \
            .neq("session_id", exclude_session_id) \
            .order("updated_at", desc=True) \
            .limit(1) \
            .execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logging.error(f"Error fetching previous session for user {user_id}: {e}")
        return None
