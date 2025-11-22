SYNONYMS = {
    "bus": ["bus", "coach", "cw", "shuttle"],
    "mrt": ["mrt", "train", "subway", "station"],
    "parking": ["parking", "car park", "park my car", "vehicle"],
    "exchange": ["exchange", "money changer", "currency", "fx", "rate", "ringgit"],
    "sim": ["sim", "esim", "mobile data", "roaming", "data"],
    "vep": ["vep", "vehicle entry permit", "register vep", "vep portal"],
    "touch n go": ["touch n go", "tng", "touch 'n go", "touch ’n go"],
    "ktm": ["ktm", "train", "shuttle", "tebrau"],
    "payment": ["payment", "pay", "digital payment", "card", "wallet", "apps"],
    "checkpoint": ["checkpoint", "ciq", "border", "cross", "crossing", "immigration"],
    "city square": ["city square", "jb town", "mall"],
}

def expand_query_with_synonyms(text: str) -> set:
    terms = set()
    words = text.lower().split()
    for word in words:
        if word in SYNONYMS:
            terms.update(SYNONYMS[word])
        else:
            terms.add(word)
    return terms
import re
from typing import List, Dict, Any, Optional, Tuple
from .fuzzy_utils import fuzzy_match


# Minimal keyword set for first cut. Tune via logs.
TRAVEL_KEYWORDS = {
    # border and timing
    "causeway", "checkpoint", "ciq", "border", "peak", "off-peak", "queue", "jam", "cross", "crossing", "immigration",
    # transport
    "bus", "160", "170", "170x", "950", "cw", "ts", "shuttle", "tebrau", "ktm", "grab", "taxi", "car", "train", "mrt", "public transport", "mode", "route", "travel mode",
    # driving and payments
    "vep", "register vep", "vehicle entry permit", "vep portal", "vep registration", "touch n go", "touch ’n go", "touch 'n go", "tng", "parking", "pay", "payment", "digital payment",
    # areas
    "mount austin", "austin", "molek", "skudai", "permas", "bukit indah", "century garden", "jb town", "city square",
    # telecom and money
    "sim", "esim", "roaming", "mobile data", "data", "dcc", "exchange", "fx", "rate", "currency", "money", "cash", "apps", "wallet",
    # time/day
    "weekday", "weekend", "day", "time", "hour", "schedule", "duration", "how long", "best day", "best time",
}


def extract_keywords(text: str) -> List[str]:
    t = text.lower()
    hits = []
    for k in TRAVEL_KEYWORDS:
        if k in t:
            hits.append(k)
    return hits


def extract_links(text: str) -> List[Dict[str, str]]:
    urls = re.findall(r"https?://[^\s)]+", text)
    # Simple labeling: domain-based
    labelled = []
    for u in urls:
        label = u
        if "ktmb.com.my" in u:
            label = "Official KTM Site"
        elif "vep.jpj.gov.my" in u:
            label = "JPJ VEP Portal"
        elif "touchngo.com.my" in u:
            label = "Touch 'n Go"
        elif "xe.com" in u:
            label = "XE Exchange Rates"
        labelled.append({"text": label, "url": u})
    return labelled


def score_row(row: Dict[str, Any], kw_hits: List[str]) -> float:
    score = 0.0
    tags = set((row.get("tags") or []))
    # Tag overlap bonus
    overlap = 0
    for k in kw_hits:
        if k in tags:
            overlap += 1
    score += overlap * 1.5
    # Phrase presence in question/answer
    q = (row.get("question") or "").lower()
    a = (row.get("answer") or "").lower()
    phrase_hits = sum(1 for k in kw_hits if (k in q or k in a))
    score += phrase_hits * 1.0
    # top10 boost
    if row.get("top10"):
        score += 2.0
    # link presence boost
    if extract_links(a):
        score += 0.5
    return score


def query_candidates(supabase, kw_hits: List[str]) -> List[Dict[str, Any]]:
    # Build an OR filter across question/answer for present keywords
    ors = []
    for k in kw_hits:
        like = f"%{k}%"
        ors.append(f"question.ilike.{like}")
        ors.append(f"answer.ilike.{like}")
    sel = supabase.table("travel_faq").select("id,category,question,answer,tags,last_updated,top10,dynamic,link")
    if ors:
        sel = sel.or_(",".join(ors))
    # Reasonable cap
    res = sel.limit(24).execute()
    return res.data or []


def build_structured_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    links = extract_links(row.get("answer") or "")
    payload = {
        "status": "success",
        "flow": "travel_faq",
        "data": {
            "faq_id": row.get("id"),
            "matched_question": row.get("question"),
            "answer": row.get("answer"),
            "is_dynamic": bool(row.get("dynamic")),
            "links": links,
        },
    }
    return payload


def handle_travel_query(user_text: str, supabase, keyword_threshold: int = 1) -> Optional[Dict[str, Any]]:
    import logging
    logger = logging.getLogger("travel_flow")
    logger.info(f"User query: {user_text}")
    expanded_terms = expand_query_with_synonyms(user_text)
    logger.info(f"Expanded query terms: {expanded_terms}")
    # Pass 1: Filter FAQs by expanded keywords
    all_faqs = supabase.table("travel_faq").select("id,category,question,answer,tags,last_updated,top10,dynamic,link").limit(100).execute().data or []
    candidate_faqs = []
    for row in all_faqs:
        faq_text = (row.get("question") or "") + " " + (row.get("answer") or "")
        if any(term in faq_text.lower() for term in expanded_terms):
            candidate_faqs.append(row)
    logger.info(f"Keyword candidate count: {len(candidate_faqs)}")
    best = None
    if candidate_faqs:
        faq_questions = [row["question"] for row in candidate_faqs]
        idx = fuzzy_match(user_text, faq_questions, threshold=65)
        logger.info(f"Fuzzy match index: {idx}")
        if idx is not None:
            best = candidate_faqs[idx]
            logger.info(f"Fuzzy matched question: {best.get('question')}")
        else:
            logger.info("No fuzzy match found in candidates. Fallback to LLM triggered.")
            return None
    else:
        logger.info("No candidates found after keyword/synonym filtering. Fallback to LLM triggered.")
        return None
    payload = build_structured_payload(best)
    disclaimer = ""
    if bool(best.get("dynamic")):
        disclaimer = "\n\nNote: Live information can change — please verify with official sources."
    return {
        "response": (best.get("answer") or "").strip() + disclaimer,
        "meta": {
            "type": "travel_faq",
            "travel": payload,
        }
    }
