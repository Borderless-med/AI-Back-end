from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

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
    user_id: str

class ChatIntent(str, Enum):
    FIND_CLINIC = "find_clinic"
    BOOK_APPOINTMENT = "book_appointment"
    GENERAL_DENTAL_QUESTION = "general_dental_question"
    REMEMBER_SESSION = "remember_session"
    OUT_OF_SCOPE = "out_of_scope"

class GatekeeperDecision(BaseModel):
    intent: ChatIntent
