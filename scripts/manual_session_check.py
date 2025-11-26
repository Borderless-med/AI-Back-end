import os
import time
import jwt
from dotenv import load_dotenv
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app

load_dotenv()

SECRET = os.getenv("SUPABASE_JWT_SECRET")
assert SECRET, "SUPABASE_JWT_SECRET not set"

client = TestClient(app)

def make_token():
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "role": "authenticated",
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")

def post_chat(history, session_id=None):
    headers = {"X-Authorization": f"Bearer {make_token()}"}
    payload = {
        "history": history,
        "applied_filters": {},
        "candidate_pool": [],
        "booking_context": {},
        "session_id": session_id,
        "user_id": None,
    }
    r = client.post("/chat", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()

if __name__ == "__main__":
    # Step 1: Ask for clinics (should prompt for country)
    res1 = post_chat([{"role": "user", "content": "find best clinics for root canal"}])
    sid = res1.get("session_id")
    assert sid, "No session_id returned"
    meta1 = res1.get("meta", {})
    print("Step1 response meta:", meta1)
    assert meta1.get("type") == "location_prompt", "Expected location prompt on first turn"

    # Step 2: Provide country (SG) and service together to trigger ranking
    res2 = post_chat([{"role": "user", "content": "In Singapore, I need root canal"}], session_id=sid)
    # Step 3: Now ask for clinics again to trigger ranking with location set
    res3 = post_chat([{"role": "user", "content": "find clinics for root canal"}], session_id=sid)
    pool = res3.get("candidate_pool", [])
    print("Top clinics count:", len(pool))
    for i, c in enumerate(pool, start=1):
        print(f"  {i}. {c.get('name')} (rating={c.get('rating')}, reviews={c.get('reviews')})")
    assert len(pool) == 3, f"Expected 3 clinics, got {len(pool)}"
    af = res3.get("applied_filters", {})
    assert "direct_clinic" not in af, "Should not lock to a direct clinic on generic query"

    print("Manual session check passed: top-3 behavior verified.")
