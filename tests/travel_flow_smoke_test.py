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
client = TestClient(app)


pytestmark = pytest.mark.skipif(not TEST_JWT, reason="No TEST_JWT and could not generate one")


def chat(payload):
    headers = {"X-Authorization": f"Bearer {TEST_JWT}"}
    r = client.post("/chat", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def base_payload(text):
    return {
        "history": [{"role": "user", "content": text}],
        "applied_filters": {},
        "candidate_pool": [],
        "booking_context": {},
        "session_id": None,
        "user_id": None,
    }


def test_travel_tebrau_link():
    res = chat(base_payload("Is the Shuttle Tebrau running?"))
    assert res.get("meta", {}).get("type") == "travel_faq"
    travel = res["meta"]["travel"]
    assert travel["status"] == "success"
    assert travel["flow"] == "travel_faq"
    links = travel["data"].get("links", [])
    assert any("ktmb.com.my" in l.get("url", "") for l in links)


def test_travel_vep_portal():
    res = chat(base_payload("Where do I register VEP for my SG car?"))
    assert res.get("meta", {}).get("type") == "travel_faq"
    travel = res["meta"]["travel"]
    data = travel["data"]
    assert "VEP" in (data.get("matched_question") or "") or "VEP" in (data.get("answer") or "")


def test_non_travel_qna_fallback():
    res = chat(base_payload("How should I floss properly?"))
    # Should not necessarily be travel; allow Q&A flow
    assert res.get("meta", {}).get("type") != "travel_faq"
