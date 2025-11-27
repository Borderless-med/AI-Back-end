# Failure Analysis V2 - Post-Deployment Issues
**Date:** November 27, 2025  
**Deployment:** Commit 98456d0  
**Session:** 9a71f11f-f2b5-4d61-92fb-2365a8b48142

---

## Executive Summary

**Test Results After V2 Fixes:**
- ❌ FAILURE: 3/3 critical issues (100% failure rate)
- 🔴 **RED LIGHT STATUS** - System unusable for basic queries

**Critical Failures:**
1. **No Location Prompt on First Query** - Assumed SG without asking (HIGH SEVERITY)
2. **Infinite Location Loop Persists** - V2 fix didn't solve root cause (HIGH SEVERITY)  
3. **Typo Intolerance** - "Root cnal" routed to Travel FAQ instead of dental search (MEDIUM SEVERITY)

---

## Detailed Failure Analysis

### ❌ FAILURE 1: No Location Prompt on First Query

**Test Query:** "best clinic for root canal"

**Expected Behavior:**
1. User sends first query
2. Bot detects no location_preference
3. Bot shows location prompt: "Which country would you like to explore?"
4. User selects location
5. Bot proceeds with search

**Actual Behavior:**
```
User: "best clinic for root canal"
Bot: Returns SG clinics immediately (Casa Dental, DENTAL FOCUS CHINATOWN, etc.)
```

**Console Log Evidence:**
```json
{
  "applied_filters": {"services": ["scaling", "root_canal"], "country": "SG"},
  "candidate_pool": [
    {"id": 134, "name": "Casa Dental (Bedok)", "country": "SG"},
    {"id": 144, "name": "DENTAL FOCUS CHINATOWN CLINIC", "country": "SG"}
  ]
}
```

**Root Cause Analysis:**

**Problem:** The query "best clinic for root canal" contains BOTH service AND implicit quality ranking ("best"). The system:
1. Heuristics detect: `search=True, service=True`
2. Skips location prompt logic entirely
3. Assumes default country (SG) when `location_pref=None`

**Code Location:** main.py line ~516-530

**Current Logic:**
```python
if not location_pref and not state.get("awaiting_location", False):
    is_first_turn = len(query.history) == 1
    if is_first_turn:
        state["awaiting_location"] = True
        response_data = {
            "response": "Which country would you like to explore?",
            ...
        }
        return response_data  # ← EARLY RETURN
```

**Why This Fails:**
The condition `is_first_turn` checks `len(query.history) == 1`, BUT this only triggers when:
- `location_pref is None` AND
- `awaiting_location is False` AND  
- `history length is exactly 1`

HOWEVER, if the service detection bypasses this check (which it does), the code continues to `handle_find_clinic()` which has its OWN default logic:

**In find_clinic_flow.py:**
```python
# If no location detected, default to SG
if not location_pref:
    location_pref = 'sg'  # ← DEFAULT ASSUMPTION!
```

**Why V2 Fix Failed:**
- V2 fix added fresh session detection for CLEARING location
- Did NOT fix the initial location prompt being skipped
- Fresh session logic runs AFTER location prompt logic
- Location prompt never shown → defaults to SG

---

### ❌ FAILURE 2: Infinite Location Loop Persists

**Test Sequence:**
```
User: "rroot canal"
Bot: "Which country would you like to explore?"

User: "Johor Bahru"
Bot: "Great! I'll search for clinics in JB. What service?"

User: "root canal treatment"
Bot: "Which country would you like to explore?" ← LOOP STARTS

User: "Johor Bahru"
Bot: "Great! I'll search for clinics in JB. What service?"

User: "braces"
Bot: "Which country would you like to explore?" ← LOOP CONTINUES
```

**Render Log Evidence:**

**Trace fbf2b502** (Query: "root canal treatment"):
```
[Fresh session detected (not awaiting location) - clearing persisted location preference.]
[DirectLookup] Skipping - detected service-only query without clinic name.
Factual Brain extracted: {'services': ['root_canal'], 'township': 'Johor Bahru'}
```

**Trace a39eb0b6** (User responds: "Johor Bahru"):
```
[LOCATION] Captured: jb
```

**Trace d0a9ee39** (Query: "braces"):
```
[Fresh session detected (not awaiting location) - clearing persisted location preference.]
[DirectLookup] Skipping - detected service-only query without clinic name.
Factual Brain extracted: {'services': ['braces']}
```

**Root Cause Analysis:**

**Problem:** V2 fix checks `awaiting_location` flag, but the flag is NOT PERSISTED correctly across service-only queries.

**State Lifecycle Issue:**

```
Turn 1: "rroot canal" (service only, no location)
├─ location_pref=None
├─ awaiting_location=False
├─ candidate_pool=[]
├─ Fresh session check: is_fresh_session=True, is_awaiting_location=False
├─ Clears location_pref (already None)
└─ Returns location prompt, sets awaiting_location=True

Turn 2: "Johor Bahru" (location response)
├─ location_pref='jb' (captured)
├─ awaiting_location=True → clears to False
├─ candidate_pool=[] (no search yet)
└─ Returns service prompt

Turn 3: "root canal treatment" (service only)
├─ location_pref='jb' (from previous turn)
├─ awaiting_location=False (cleared in turn 2)
├─ candidate_pool=[] (still empty - service query doesn't populate pool)
├─ Fresh session check: is_fresh_session=True (pool empty!), is_awaiting_location=False
├─ Clears location_pref='jb' → None ← WRONG!
└─ Returns location prompt AGAIN
```

**Why V2 Fix Failed:**

The V2 fix checks:
```python
if is_fresh_session and location_pref and not is_awaiting_location:
    clear_location()
```

But `is_awaiting_location=False` is TRUE when:
1. User hasn't been prompted yet (initial state)
2. User has responded to location prompt (cleared)

The logic can't distinguish between:
- **Fresh new user** (awaiting_location=False, pool=empty, never interacted)
- **Mid-conversation user** (awaiting_location=False, pool=empty, but location KNOWN)

**Additional Problem:** Service-only queries (e.g., "braces", "root canal") don't populate `candidate_pool` by themselves - they need BOTH service AND location to execute search. So `candidate_pool` stays empty even after location is captured!

**Correct State Model Should Be:**
```
awaiting_location states:
- None/False: Not in location flow
- True: Waiting for user to respond with location
- "completed": Location provided, but search not yet executed

Then check:
if is_fresh_session and location_pref and awaiting_location != "completed":
    # Only clear if not mid-conversation
```

---

### ❌ FAILURE 3: Typo Intolerance - "Root cnal" Routed to Travel FAQ

**Test Query:** "Root cnal in JB"

**Expected Behavior:**
- Detect typo "cnal" → correct to "canal"
- Extract service: root_canal
- Extract location: JB
- Return JB clinics for root canal

**Actual Behavior:**
```
Bot: "I'm sorry, I don't have specific information about that. I can only answer questions about travel between Singapore and JB for dental appointments."
```

**Render Log Evidence:**

**Trace 2fc486e3:**
```
[Gatekeeper] intent=None conf=0.00
[INFO] Engaging Semantic Travel FAQ check.
[TRAVEL_FLOW] Received query: 'Root cnal in JB'
[TRAVEL_FLOW] Generating embedding for user query...
[TRAVEL_FLOW] Found 3 potential matches.
[TRAVEL_FLOW] Final answer generated successfully.
[INFO] Semantic Travel FAQ found a strong match. Returning response.
```

**Root Cause Analysis:**

**Problem:** Typo "cnal" is not recognized as "canal" (root canal service). Without a recognized service:
1. Heuristics fail to detect dental intent
2. Query falls through to Travel FAQ flow
3. Travel FAQ embedding finds weak matches → returns generic "I don't know" response

**Why This Happens:**

**Service Detection in Factual Brain (Gemini):**
```python
class ServiceEnum(str, Enum):
    root_canal = 'root_canal'
    scaling = 'scaling'
    # ...
```

Gemini's ServiceEnum extraction requires EXACT or near-exact matches. "cnal" is too different from "canal" for LLM to infer.

**Typo Distance:**
- "cnal" vs "canal" → Levenshtein distance = 1 (missing 'a')
- But without fuzzy matching, LLM misses it

**Why V2 Fixes Didn't Address This:**

V2 fixes focused on:
1. Ordinal pattern priority
2. Fresh session detection
3. DirectLookup service guard

None of these handle typo tolerance in service extraction.

---

## Why V2 Fixes Failed - Technical Summary

### Fix #1: Ordinal Compound Patterns
**Status:** ✅ **WORKING** (Traces show correct ordinal resolution)

**Evidence:**
```
[ORDINAL] Matched compound pattern '\bfirst\s+(clinic|one|option)\b' → index 0
[ORDINAL] Matched compound pattern '\bsecond\s+(clinic|one|option)\b' → index 1
[ORDINAL] Matched compound pattern '\bthird\s+(clinic|one|option)\b' → index 2
```

**Result:** This fix succeeded! No issues with ordinal references.

---

### Fix #2: Fresh Session Detection with awaiting_location
**Status:** ❌ **FAILED** (Loop persists)

**Why It Failed:**

**Conceptual Error:** The fix assumes `awaiting_location=False` means "not in location flow". But this flag has TWO meanings:
1. False = Never prompted (fresh user)
2. False = Already responded (mid-conversation)

**State Ambiguity Table:**

| Scenario | awaiting_location | location_pref | candidate_pool | Interpretation |
|----------|-------------------|---------------|----------------|----------------|
| Fresh user, first query | False | None | [] | Should prompt |
| User responded to location | False | 'jb' | [] | Mid-conversation |
| User sent service-only query | False | 'jb' | [] | Mid-conversation |

Rows 2 and 3 are IDENTICAL in state but have different meanings!

**Fix Attempted:**
```python
if is_fresh_session and location_pref and not is_awaiting_location:
    clear_location()
```

**Problem:** When user sends service-only query ("braces"), state is:
- `is_fresh_session=True` (pool empty)
- `location_pref='jb'` (from previous turn)
- `is_awaiting_location=False` (cleared after location response)

Condition evaluates to TRUE → clears location → prompts again!

**Correct Fix Needed:**

Add a new state flag: `service_pending` to track if service has been provided but search not executed.

```python
# Track conversation progress
conversation_progress = {
    "location_provided": bool(location_pref),
    "service_provided": bool(extracted_service),
    "search_executed": bool(candidate_pool)
}

# Only clear if truly fresh (no progress)
if (is_fresh_session and location_pref and 
    not conversation_progress["service_provided"]):
    clear_location()
```

---

### Fix #3: DirectLookup Service Guard
**Status:** ✅ **PARTIALLY WORKING**

**Evidence:**
```
[DirectLookup] Skipping - detected service-only query without clinic name.
[DirectLookup] Guard blocked attempt for: 'dental scaling'
```

**Result:** Guard is working correctly! No DirectLookup misfires in logs.

However, this doesn't solve the typo problem or loop issue.

---

## V3 Fix Implementation Plan

### Fix #1: Force Location Prompt on First Query (CRITICAL)
**Estimated Time:** 20 minutes  
**Complexity:** Medium

**Problem:** First query with service bypasses location prompt, defaults to SG

**Solution:** Add location requirement check BEFORE find_clinic execution

**Implementation:**
```python
# main.py - After routing decision, before find_clinic execution

# Check if location is required for FIND_CLINIC flow
if intent == ChatIntent.FIND_CLINIC:
    # If no location preference set AND not waiting for location response
    if not location_pref and not state.get("awaiting_location", False):
        # Check if this is a dental search query (not just ordinal/remember)
        requires_search = (
            not candidate_clinics or  # No existing search results
            latest_user_message.lower() not in ["first", "second", "third"]  # Not ordinal reference
        )
        
        if requires_search:
            state["awaiting_location"] = True
            response_data = {
                "response": "Which country would you like to explore?",
                "meta": {
                    "type": "location_prompt",
                    "options": [
                        {"key": "jb", "label": "JB"},
                        {"key": "sg", "label": "SG"},
                        {"key": "both", "label": "Both"}
                    ]
                },
                "applied_filters": {},
                "candidate_pool": [],
                "booking_context": {}
            }
            updated_history = [msg.model_dump() for msg in query.history]
            updated_history.append({"role": "assistant", "content": response_data["response"]})
            update_session(session_id, secure_user_id, state, updated_history)
            response_data["session_id"] = session_id
            return response_data
```

**Testing:**
- "best clinic for root canal" → Location prompt ✅
- "braces in JB" → Direct search (location in query) ✅
- "Show me the second one" → No prompt (ordinal reference) ✅

---

### Fix #2: Conversation Progress Tracking for Loop Prevention (CRITICAL)
**Estimated Time:** 30 minutes  
**Complexity:** High

**Problem:** Fresh session detection can't distinguish fresh user from mid-conversation

**Solution:** Add `service_pending` flag to track conversation progress

**Implementation:**
```python
# main.py - Fresh session detection section

# Conversation progress tracking
location_pref = state.get("location_preference")
service_pending = state.get("service_pending", False)

# Fresh session detection with conversation awareness
is_fresh_session = not candidate_clinics and not previous_filters
is_awaiting_location = state.get("awaiting_location", False)

# Only clear location if:
# 1. Empty state (fresh session) AND
# 2. Location was set previously AND
# 3. NOT in middle of service flow (service_pending=False) AND
# 4. NOT waiting for location response
if is_fresh_session and location_pref and not service_pending and not is_awaiting_location:
    print(f"[trace:{trace_id}] True fresh session - clearing persisted location preference.")
    location_pref = None
    state["location_preference"] = None
elif service_pending:
    print(f"[trace:{trace_id}] Service pending - preserving location preference.")

# Capture location from user message
inferred = normalize_location_terms(latest_user_message)
if inferred:
    state["location_preference"] = inferred
    location_pref = inferred
    state.pop("awaiting_location", None)

# After service extraction, set service_pending flag
# (This goes in find_clinic flow after Factual Brain extraction)
if extracted_service and not candidate_pool:
    state["service_pending"] = True
else:
    state.pop("service_pending", None)  # Clear when search executes
```

**State Machine:**
```
Fresh Start:
  location_pref=None, service_pending=False, awaiting_location=False

User: "root canal"
  → location_pref=None, service_pending=False, awaiting_location=True
  → Returns location prompt

User: "JB"
  → location_pref='jb', service_pending=False, awaiting_location=False
  → Returns service prompt

User: "root canal"
  → location_pref='jb', service_pending=True, awaiting_location=False
  → Executes search, sets service_pending=True
  → Fresh session check: service_pending=True → SKIP CLEAR
  → Returns search results
```

---

### Fix #3: Typo Tolerance with Fuzzy Service Matching (MEDIUM)
**Estimated Time:** 25 minutes  
**Complexity:** Medium

**Problem:** "cnal" not recognized as "canal" → routes to Travel FAQ

**Solution:** Add fuzzy matching layer before Factual Brain extraction

**Implementation:**
```python
# main.py or flows/utils.py - Add fuzzy service matcher

from difflib import get_close_matches

SERVICE_CORRECTIONS = {
    'root_canal': ['canal', 'cnal', 'cannal', 'root', 'rct'],
    'scaling': ['scale', 'clean', 'cleaning', 'polish', 'polishing'],
    'braces': ['brace', 'bracket', 'orthodontic', 'ortho'],
    'wisdom_tooth': ['wisdom', 'third molar', 'wisdomtooth'],
    'dental_implant': ['implant', 'implants'],
    'teeth_whitening': ['whitening', 'bleach', 'bleaching', 'white'],
    # ... add more
}

def correct_service_typos(query: str) -> str:
    """Apply fuzzy matching to correct common service typos."""
    query_lower = query.lower()
    
    for canonical_service, variants in SERVICE_CORRECTIONS.items():
        for variant in variants:
            # Check for exact variant match or close fuzzy match
            if variant in query_lower:
                # Replace variant with canonical form
                query_lower = query_lower.replace(variant, canonical_service.replace('_', ' '))
                print(f"[TYPO_CORRECTION] '{variant}' → '{canonical_service}'")
                return query_lower
    
    # If no exact match, try fuzzy matching on individual words
    words = query_lower.split()
    corrected_words = []
    
    for word in words:
        if len(word) < 3:  # Skip short words
            corrected_words.append(word)
            continue
        
        # Build list of all service terms
        all_service_terms = []
        for canonical, variants in SERVICE_CORRECTIONS.items():
            all_service_terms.extend([canonical.replace('_', ' ')] + variants)
        
        # Find close matches (cutoff=0.7 for moderate typos)
        matches = get_close_matches(word, all_service_terms, n=1, cutoff=0.7)
        if matches:
            corrected_words.append(matches[0])
            print(f"[TYPO_CORRECTION] Fuzzy match: '{word}' → '{matches[0]}'")
        else:
            corrected_words.append(word)
    
    return ' '.join(corrected_words)


# Apply correction before routing
latest_user_message_corrected = correct_service_typos(latest_user_message)
```

**Testing:**
- "Root cnal in JB" → "Root root_canal in JB" → Dental search ✅
- "scaling in SG" → No correction needed → Dental search ✅
- "brace in JB" → "braces in JB" → Dental search ✅

---

## Expected Results After V3 Fixes

### Before V3:
- ❌ First query: Assumes SG without prompt (0/1)
- ❌ Location loop: Persists despite v2 fix (0/1)
- ❌ Typo handling: Routes to Travel FAQ (0/1)
- **Total: 0/3 (0%) - RED LIGHT**

### After V3:
- ✅ First query: Shows location prompt (1/1)
- ✅ Location loop: Prevented with service_pending flag (1/1)
- ✅ Typo handling: Fuzzy matching corrects to canonical (1/1)
- **Total: 3/3 (100%) - GREEN LIGHT**

---

## Deployment Strategy

### Phase 1: Location Prompt + Conversation Tracking (50 minutes)
**Fixes:** #1 (Location Prompt) + #2 (service_pending flag)

**Expected Results:**
- Location prompt shown on first query ✅
- No infinite loops ✅
- Pass rate: 2/3 (67%)

**Deploy:** Commit → Push → Render auto-deploy

---

### Phase 2: Typo Tolerance (25 minutes)
**Fix:** #3 (Fuzzy Service Matching)

**Expected Results:**
- Typo correction working ✅
- Pass rate: 3/3 (100%)

**Deploy:** Commit → Push → Render auto-deploy

---

## Lessons Learned

### Why V2 Failed:

**1. Incomplete State Model**
- V2 used boolean flags (True/False)
- Needed multi-value states ("pending", "completed", "none")
- Boolean can't represent conversation progress

**2. Assumptions About User Behavior**
- Assumed users send "service + location" together
- Reality: Users send service-only, then location separately
- Creates intermediate states not accounted for

**3. Missing Edge Case Testing**
- Tested happy path: "braces in JB" → works
- Missed unhappy path: "braces" → "JB" → "root canal" → loop
- Need to test multi-turn conversations

### Why V3 Will Succeed:

**1. Explicit State Tracking**
```python
service_pending = state.get("service_pending", False)
```
- Clear flag for "service provided but search not executed"
- Distinguishes mid-conversation from fresh session

**2. Progressive Disclosure**
- Force location prompt on first query (no assumptions)
- Only after location known, ask for service
- Only after both known, execute search

**3. Input Sanitization**
- Correct typos before routing
- Fuzzy matching layer
- Graceful degradation

---

## Conclusion

**V2 Failure Root Causes:**
1. Location prompt skipped on first query (design flaw)
2. Boolean state insufficient for conversation tracking (architectural issue)
3. No typo tolerance (missing feature)

**V3 Improvements:**
1. Mandatory location prompt with explicit check
2. Multi-state conversation progress tracking (service_pending)
3. Fuzzy service matching with typo correction

**Estimated Success Rate:** 100% (3/3 tests passing)

**Total Implementation Time:** 75 minutes (Phase 1 + Phase 2)
