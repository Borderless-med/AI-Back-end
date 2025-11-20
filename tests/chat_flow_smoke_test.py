"""Basic smoke tests for chat endpoint.
Run locally with: python -m pytest -q tests/chat_flow_smoke_test.py

If TEST_JWT is not provided, attempt to generate one using SUPABASE_JWT_SECRET for ephemeral testing.
"""
import os
import time
import jwt
import pytest
from fastapi.testclient import TestClient
from main import app

TEST_JWT = os.getenv("TEST_JWT")
if not TEST_JWT:
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if secret:
        payload = {
            "sub": "00000000-0000-0000-0000-000000000001",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "role": "authenticated",
        }
        try:
            TEST_JWT = jwt.encode(payload, secret, algorithm="HS256")
        except Exception:
            TEST_JWT = None

if not TEST_JWT:
    pytest.skip("No TEST_JWT available and failed to generate from SUPABASE_JWT_SECRET", allow_module_level=True)

client = TestClient(app)

def auth_headers():
    return {"X-authorization": f"Bearer {TEST_JWT}"}

def test_qna_root_canal_explanation():
    """Pure informational question should stay in Q&A and include disclaimer."""
    payload = {
        "history": [{"role": "user", "content": "What is root canal treatment?"}]
    }
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "response" in data
    txt = data["response"].lower()
    # Should NOT have candidate_pool clinics list (or at most empty) for pure Q&A
    assert not data.get("candidate_pool") or len(data.get("candidate_pool", [])) <= 0
    # Should contain disclaimer
    assert "disclaimer:" in txt


def test_find_root_canal_with_action_word():
    """Query with action word should trigger clinic search."""
    payload = {
        "history": [{"role": "user", "content": "Find root canal clinics in JB"}]
    }
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data.get("candidate_pool", [])) > 0, "Expected clinics for search query"
    assert data.get("applied_filters", {}).get("country") in ("MY", "SG", "SG+MY")


def test_direct_clinic_lookup():
    """Specific clinic name should return a single detail card with meta.type == clinic_detail."""
    payload = {
        "history": [{"role": "user", "content": "Tell me all about Koh Dental in JB"}]
    }
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("meta", {}).get("type") == "clinic_detail"
    assert len(data.get("candidate_pool", [])) == 1


def test_question_with_service_but_no_action():
    """Service keyword without action words should remain Q&A."""
    payload = {
        "history": [{"role": "user", "content": "How painful is a root canal?"}]
    }
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    # Expect Q&A style response (no forced clinic list)
    assert len(data.get("candidate_pool", [])) == 0
    assert "disclaimer:" in data.get("response", "").lower()


def test_booking_flow_affirmative_transition():
    """Simple booking confirmation path (requires previous state). This is a minimal state simulation."""
    # First emulate a clinic search establishing candidate_pool & filters
    initial = {
        "history": [{"role": "user", "content": "Find scaling clinics in JB"}]
    }
    r1 = client.post("/chat", json=initial, headers=auth_headers())
    assert r1.status_code == 200, r1.text
    data1 = r1.json()
    session_id = data1.get("session_id")
    assert session_id
    # Now trigger booking intent with a clinic position reference
    booking_start = {
        "history": [
            {"role": "user", "content": "Find scaling clinics in JB"},
            {"role": "assistant", "content": data1.get("response", "")},
            {"role": "user", "content": "Book first one"}
        ],
        "session_id": session_id,
        "applied_filters": data1.get("applied_filters", {}),
        "candidate_pool": data1.get("candidate_pool", [])
    }
    r2 = client.post("/chat", json=booking_start, headers=auth_headers())
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    # Should move into confirming_details or gathering_info
    booking_ctx = data2.get("booking_context", {})
    assert booking_ctx.get("status") in {"confirming_details", "gathering_info"}


def test_qm_brand_typo_direct_detail():
    """Brand with typo should return a single Q&M branch detail card."""
    payload = {
        "history": [{"role": "user", "content": "Q & M Dentel singapore"}]
    }
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("meta", {}).get("type") == "clinic_detail"
    assert len(data.get("candidate_pool", [])) == 1
    # country should be SG for this query
    assert data.get("applied_filters", {}).get("country") == "SG"


def test_qm_brand_variants():
    """Q&M brand variants should also resolve to a direct detail card."""
    for utterance in ["Q and M dental", "q&m dental"]:
        payload = {"history": [{"role": "user", "content": utterance}]}
        r = client.post("/chat", json=payload, headers=auth_headers())
        assert r.status_code == 200, (utterance, r.text)
        data = r.json()
        assert data.get("meta", {}).get("type") == "clinic_detail"
        assert len(data.get("candidate_pool", [])) == 1


def test_nonsense_name_no_direct_match():
    """Nonsense clinic name should not fall back to generic top-3; return no-match."""
    payload = {"history": [{"role": "user", "content": "Zeta Smile Hub JB"}]}
    r = client.post("/chat", json=payload, headers=auth_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    # Expect explicit no-match meta and empty candidate list
    assert data.get("meta", {}).get("type") == "no_direct_match"
    assert len(data.get("candidate_pool", [])) == 0

if __name__ == "__main__":
    # Simple manual run without pytest
    for fn in [
        test_qna_root_canal_explanation,
        test_find_root_canal_with_action_word,
        test_direct_clinic_lookup,
        test_question_with_service_but_no_action,
    ]:
        try:
            fn()
            print(f"[OK] {fn.__name__}")
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
