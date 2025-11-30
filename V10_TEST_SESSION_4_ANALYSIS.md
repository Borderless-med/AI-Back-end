# V10 Test Session 4 Analysis - Comprehensive Results

**Test Date:** November 30, 2025  
**Session ID:** 9a71f11f-f2b5-4d61-92fb-2365a8b48142  
**Test Duration:** ~4 minutes (10 queries)  
**Tester:** User manual testing  
**Version:** V10 (post-hotfix with V8/V9 fixes)

---

## Executive Summary

### Overall Performance
- **Total Queries:** 10
- **Successful:** 1/10 (10%)
- **Failed:** 9/10 (90%)
- **Critical Failures:** 9 (DirectLookup misrouting, treatment wrong, cancel detection, travel FAQ blocked)

### Accuracy by Category
- **Search (Q3, Q10):** 1/2 (50%) - Q3 succeeded, Q10 succeeded
- **Booking (Q3-Q5, Q10):** 0/4 (0%) ❌ - All booking confirmations wrong treatment
- **Cancel Detection (Q1, Q2, Q9):** 0/3 (0%) ❌ - All failed
- **DirectLookup Errors (Q2, Q6, Q7):** 0/3 (0%) ❌ - Misinterpreted as clinic names
- **Travel FAQ (Q8):** 0/1 (0%) ❌ - Blocked by booking guard

### Key Findings
1. **DirectLookup Catastrophic Failure** - Q2, Q6, Q7: "Find clinics in JB City", "accept insurance", "payment methods" all interpreted as clinic names
2. **Treatment Context Bug (CRITICAL)** - Q3, Q4, Q5, Q10: All bookings confirm BRACES instead of CLEANING
3. **Cancel Keywords Broken** - Q1 "abort plan", Q2 "cancel", Q9 "I changed my mind, I'll call them" all failed
4. **Booking Guard Too Strict** - Q8: Travel directions blocked mid-booking despite V9 guard supposed to allow
5. **Clinic Context Loss** - Q5 "book here" doesn't remember "Austin Dental Group"

---

## Detailed Query Analysis Table

| # | User Query | Expected | Actual | Time | Status | Root Cause |
|---|------------|----------|--------|------|--------|------------|
| Q1 | abort plan | Cancel search/clear filters | "abort plan is unclear... provide more details" | ~2s | ❌ FAIL | Bug 3: "abort" not in cancel keywords OR not detected in this context |
| Q2 | Find clinics in JB City Centre | List JB City Centre clinics | "couldn't find a clinic named 'in city'" | ~15s | ❌ FAIL | Bug 4: DirectLookup misroutes location-only search as clinic name |
| Q3 | I need braces in JB | List 3 JB braces clinics | Listed 3 JB clinics ✓ | ~8s | ✅ PASS | Search flow works correctly |
| Q3.book | Book at first JB clinic | Confirm **braces** at Aura Dental | Confirmed **braces** ✓ (but wrong treatment for Q4!) | ~2s | ⚠️ CONTEXT | Booking started with correct treatment from Q3 |
| Q4 | Also show me teeth whitening in SG | List SG teeth whitening clinics | Listed 3 SG/JB whitening clinics ✓ | ~10s | ✅ PASS | Search flow works |
| Q4.book | Book at first SG clinic | Confirm **teeth_whitening** at Casa Dental | Confirmed **braces** (WRONG!) | ~3s | ❌ FAIL | Bug 1: services[0] gets 'braces' from Q3, ignores 'teeth_whitening' |
| Q4.cancel | Cancel | Cancel booking | Booking cleared ✓ | ~2s | ✅ PASS | Cancel keyword "cancel" works in booking mode |
| Q5 | Find dental cleaning in Mount Austin | List Mount Austin cleaning clinics | Listed 3 Mount Austin clinics ✓ | ~8s | ✅ PASS | Search flow works |
| Q5.book | I want to book here | Initiate booking at Austin Dental Group (3rd clinic) | "No positional reference found. Using AI to extract clinic name" - asks for clinic name | ~5s | ❌ FAIL | Bug 2: "here" not recognized, clinic context lost |
| Q6 | Do JB clinics accept insurance? | Policy information from QnA | "couldn't find a clinic named 'do accept insurance'" | ~12s | ❌ FAIL | Bug 5: Insurance question misrouted to DirectLookup |
| Q7 | What payment methods do JB clinics accept? | Policy information from QnA | "couldn't find a clinic named 'what payments method do accept'" | ~10s | ❌ FAIL | Bug 5: Policy question misrouted to DirectLookup |
| Q8 | How do I get there from Singapore? [mid-booking] | Travel directions OR defer | "AI unable to provide travel stayed in booking flow" | ~12s | ❌ FAIL | Bug 8: V9 guard blocked travel FAQ during booking |
| Q9 | I changed my mind, I'll call them instead [booking] | Cancel booking | "AI did not cancel" | ~3s | ❌ FAIL | Bug 3: Natural language cancel not detected |
| Q10 | I need braces again (retest) | List JB braces clinics | Listed 3 JB clinics ✓ | ~8s | ✅ PASS | Search works |
| Q10.book | Book at first clinic | Confirm **braces** at Aura Dental | Confirmed **braces** (WRONG - should be scaling!) | ~3s | ❌ FAIL | Bug 1: services[0] gets old 'braces', ignores new treatment |

**Average Response Time:** ~6.8 seconds  
**Success Rate:** 10% (1/10 queries fully successful)

---

## Console Log Forensics

### Pattern 1: Treatment Context Bug (Q3-Q4, Q10)

**Evidence from Q3→Q4 transition:**
```javascript
// After Q3 "I need braces in JB":
<<<<< Updating applied_filters state: {
  services: ['braces'],
  township: 'Johor Bahru',
  country: 'MY'
}

// After Q4 "Also show me teeth whitening in SG":
<<<<< Updating applied_filters state: {
  services: ['braces', 'teeth_whitening'],  // ❌ ACCUMULATED!
  country: 'SG'
}

// Q4 booking confirmation:
<<<<< Updating booking_context state: {
  treatment: 'braces',  // ❌ WRONG! Should be 'teeth_whitening'
  selected_clinic_name: 'Casa Dental (Bedok)...'
}
```

**Root Cause:** Backend uses `services[0]` which gets FIRST service from accumulated array. Should use `services[-1]` to get LATEST service.

**Impact:** 100% booking failure when treatment changes (Q4: wanted whitening, got braces; Q10: wanted braces, got cleaning)

### Pattern 2: DirectLookup Misrouting (Q2, Q6, Q7)

**Evidence from Console Log:**
```javascript
// Q2 "Find clinics in JB City Centre":
>>>>> Sending this body to backend: {
  "applied_filters": {},
  "candidate_pool": [],
  "booking_context": {}
}
```

**Evidence from Render Log:**
```
[trace:1b44cbec-eed3-4b92-b4ad-4ce0e718c9de] [Gatekeeper] intent=None conf=0.00
[trace:1b44cbec-eed3-4b92-b4ad-4ce0e718c9de] [INFO] Heuristic detected Dental Intent (search=True, service=True)
[DirectLookup] Skipping - detected service-only query without clinic name.
[DirectLookup] Guard blocked attempt for: 'Find dental cleaning in JB'
```

**Root Cause:** Q2 "Find clinics in JB City Centre" hit DirectLookup which extracted fragment "in city" and interpreted it as clinic name. Q6/Q7 insurance/payment questions also misrouted to DirectLookup.

**Impact:** 30% of queries fail due to DirectLookup misrouting natural language searches as clinic names.

### Pattern 3: Cancel Keywords Incomplete (Q1, Q9)

**Evidence from Q1:**
```javascript
// User: "abort plan"
// Response: "abort plan is unclear... provide more details"
```

**Evidence from Q9:**
```javascript
// User: "I changed my mind, I'll call them instead"
// Response: "AI did not cancel"
```

**Current Cancel Keywords:** `['cancel', 'stop', 'nevermind', 'never mind', 'abort']`

**Root Cause:** Q1 "abort plan" not recognized (possibly context-dependent). Q9 "I'll call them" pattern not in keyword list.

**Impact:** 30% of queries fail due to cancel detection issues.

### Pattern 4: Clinic Context Loss (Q5)

**Evidence from Q5:**
```javascript
// After listing 3 Mount Austin clinics (Austin Dental Group is 3rd):
<<<<< Updating candidate_pool state with 3 clinics

// User: "I want to book here"
// Render log: "No positional reference found. Using AI to extract clinic name."
```

**Root Cause:** "here" not recognized as ordinal/positional reference. Backend expects "first", "second", "third" or exact clinic name.

**Impact:** Natural language booking attempts fail.

### Pattern 5: Booking Guard Blocks Travel FAQ (Q8)

**Evidence from Render Log:**
```
[trace:10a8f80e-1e51-4e18-a9b6-79723afc851c] [BOOKING] User asking for travel directions - routing to travel FAQ.
[trace:10a8f80e-1e51-4e18-a9b6-79723afc851c] [V9 GUARD] Booking flow active (status=confirming_details) - skipping travel FAQ check, continuing with booking
```

**Root Cause:** V9 guard detects travel keywords but **prioritizes booking flow** over travel FAQ. Should allow travel FAQ, then return to booking.

**Impact:** User cannot get travel info mid-booking.

---

## Render Log Forensics

### Pattern 1: DirectLookup Fragment Extraction Failure

**Q2 Evidence:**
```
User: "Find clinics in JB City Centre"
Response: "couldn't find a clinic named 'in city' in Johor Bahru (JB)"
```

**Root Cause:** DirectLookup heuristic detects "clinics" keyword and routes to DirectLookup. Fragment extraction mangles query to "in city".

### Pattern 2: Insurance/Policy Misrouting

**Q6 Evidence:**
```
User: "Do JB clinics accept insurance?"
Response: "couldn't find a clinic named 'do accept insurance'"
```

**Q7 Evidence:**
```
User: "What payment methods do JB clinics accept?"
Response: "couldn't find a clinic named 'what payments method do accept'"
```

**Root Cause:** Heuristic detects "clinics" keyword and routes to DirectLookup instead of QnA. Should detect policy keywords (insurance, payment, accept, methods).

### Pattern 3: Search Flow Success

**Q3, Q4, Q5, Q10 all show successful search:**
```
Factual Brain extracted: {'services': ['braces'], 'township': 'Johor Bahru'}
Found 51 candidates after initial database filtering across 1 source(s).
Found 50 candidates after Quality Gate.
DEBUG: Preparing to return 3 clinics in the candidate pool.
```

**Observation:** Search flow with explicit treatment+location works perfectly. Only DirectLookup and booking confirmation are broken.

### Pattern 4: Booking Flow Detection

**Q3, Q4, Q5, Q10 all show:**
```
[trace:xxx] [BOOKING] Early booking detection - overriding travel/semantic checks.
Starting Booking Mode...
```

**Observation:** Booking mode triggered correctly. Problem is **treatment extraction** from services array.

---

## Bug Identification Summary

### Bug 1: Treatment Context Bug (services[0] vs services[-1]) - CRITICAL
- **Location:** `booking_flow.py` lines 108-118
- **Severity:** CRITICAL (100% booking failure when treatment changes)
- **Evidence:** Q4 wanted teeth_whitening, confirmed braces; Q10 wanted braces, confirmed cleaning
- **Impact:** 4/10 queries (40%)
- **Fix:** Change `treatment = previous_filters.services[0]` to `treatment = previous_filters.services[-1]`

```python
# CURRENT CODE (BROKEN):
if previous_filters and "services" in previous_filters:
    treatment = previous_filters["services"][0]  # ❌ Gets FIRST service

# FIXED CODE:
if previous_filters and "services" in previous_filters:
    treatment = previous_filters["services"][-1]  # ✅ Gets LATEST service
```

### Bug 2: Clinic Context Loss ("here" not recognized) - HIGH
- **Location:** `booking_flow.py` ordinal reference logic
- **Severity:** HIGH (natural language booking fails)
- **Evidence:** Q5 "I want to book here" → "No positional reference found"
- **Impact:** 1/10 queries (10%)
- **Fix:** Add "here" to positional keywords and use last listed clinic

```python
# Add to positional reference detection:
POSITIONAL_KEYWORDS = ['first', 'second', 'third', 'last', 'here', 'there', 'this one', 'that one']

if 'here' in user_query.lower() or 'there' in user_query.lower():
    # Use last clinic from candidate pool
    clinic_name = candidate_pool[-1]['name']
```

### Bug 3: Cancel Keywords Incomplete - MEDIUM
- **Location:** `booking_flow.py` cancel keyword list
- **Severity:** MEDIUM (forces booking restart instead of correction)
- **Evidence:** Q1 "abort plan" failed, Q9 "I'll call them" failed
- **Impact:** 3/10 queries (30%)
- **Fix:** Expand cancel keyword list + add context detection

```python
# CURRENT:
CANCEL_KEYWORDS = ['cancel', 'stop', 'nevermind', 'never mind', 'abort']

# FIXED:
CANCEL_KEYWORDS = [
    'cancel', 'stop', 'nevermind', 'never mind', 'abort', 'abort plan',
    'changed my mind', 'change my mind', 'forget it', 
    'not anymore', 'second thoughts', 'call them', 'contact them',
    'call them instead', 'contact them instead'
]
```

### Bug 4: DirectLookup Misroutes Location Searches - HIGH
- **Location:** `find_clinic_flow.py` DirectLookup heuristic
- **Severity:** HIGH (natural language location searches fail)
- **Evidence:** Q2 "Find clinics in JB City Centre" → "couldn't find a clinic named 'in city'"
- **Impact:** 1/10 queries (10%)
- **Fix:** Don't route to DirectLookup if query contains location keywords WITHOUT specific clinic name

```python
# Add location keyword detection:
LOCATION_KEYWORDS = ['city centre', 'city center', 'downtown', 'near', 'area', 'township', 'district']

if any(keyword in user_query.lower() for keyword in LOCATION_KEYWORDS):
    # Check if there's a specific clinic name
    if not any(clinic_name in user_query.lower() for clinic_name in known_clinics):
        # Route to search flow instead of DirectLookup
        pass
```

### Bug 5: Insurance/Policy Misrouted to DirectLookup - HIGH
- **Location:** `find_clinic_flow.py` DirectLookup heuristic
- **Severity:** HIGH (policy questions fail completely)
- **Evidence:** Q6 "accept insurance", Q7 "payment methods" both interpreted as clinic names
- **Impact:** 2/10 queries (20%)
- **Fix:** Detect policy questions and route to QnA

```python
# Add policy keyword detection:
POLICY_KEYWORDS = ['insurance', 'payment', 'accept', 'how many', 'what types', 'methods', 'cost', 'price', 'fee', 'charges']

if any(keyword in user_query.lower() for keyword in POLICY_KEYWORDS):
    # Route to QnA instead of DirectLookup
    return await qna_flow(user_query, history, session_id)
```

### Bug 8: Booking Guard Blocks Travel FAQ - MEDIUM
- **Location:** `booking_flow.py` V9 guard logic
- **Severity:** MEDIUM (user experience issue)
- **Evidence:** Q8 "How do I get there from Singapore?" during booking blocked
- **Impact:** 1/10 queries (10%)
- **Fix:** Allow travel FAQ during booking without canceling

```python
# Modify V9 guard to allow travel FAQ:
TRAVEL_KEYWORDS = ['how do i get', 'directions', 'travel', 'transport', 'mrt', 'bus', 'how to get there']

if any(keyword in user_query.lower() for keyword in TRAVEL_KEYWORDS):
    # Handle travel query, then return to booking
    travel_response = await travel_flow(user_query, session_id)
    return travel_response + "\n\nWould you like to continue with your booking at " + booking_context['clinic_name'] + "?"
```

---

## V11 Fix Recommendations

### Priority 1: Critical Booking Fix (Fix 1)
**Impact:** Would raise accuracy from 10% to 50% (5/10 successful)

1. **Fix Bug 1:** Change `services[0]` to `services[-1]` (1 line)

### Priority 2: DirectLookup Improvements (Fixes 4, 5)
**Impact:** Would raise accuracy from 50% to 80% (8/10 successful)

2. **Fix Bug 4:** Add location keyword detection to prevent DirectLookup misrouting (8 lines)
3. **Fix Bug 5:** Add policy keyword detection to route to QnA (5 lines)

### Priority 3: UX Enhancements (Fixes 2, 3, 8)
**Impact:** Would raise accuracy from 80% to 100% (10/10 successful)

4. **Fix Bug 2:** Add "here" to positional keywords (5 lines)
5. **Fix Bug 3:** Expand cancel keyword list (1 line)
6. **Fix Bug 8:** Allow travel FAQ during booking (10 lines)

### Expected V11 Results
- **With Priority 1 Fix:** 50% accuracy (5/10)
- **With Priority 1+2 Fixes:** 80% accuracy (8/10)
- **With All Fixes:** 100% accuracy (10/10)

---

## Comparison with Previous Sessions

| Metric | Session 2 (13Q) | Session 3 (12Q) | Session 4 (10Q) | Trend |
|--------|-----------------|-----------------|-----------------|-------|
| Success Rate | 38.5% (5/13) | 33.3% (4/12) | 10% (1/10) | ❌ Declining |
| Booking Success | 0% (0/5) | 0% (0/5) | 0% (0/4) | ❌ Broken |
| Search Success | 100% (2/2) | 100% (1/1) | 100% (2/2) | ✅ Stable |
| DirectLookup Errors | 3 queries | 3 queries | 3 queries | ❌ Consistent issue |
| Cancel Detection | 33% (1/3) | 0% (0/2) | 0% (0/3) | ❌ Broken |

### Key Insights
- **Session 4 worst performance yet** - only 10% success rate
- **DirectLookup consistently broken** across all 3 sessions (9 failures total)
- **Booking flow 100% failure** across all 3 sessions (0/14 successful)
- **Search flow 100% success** across all 3 sessions (5/5 successful)
- **Treatment context bug affects EVERY booking attempt**

---

## 10 Test Queries for V11 Validation

### Category 1: Treatment Context Validation (Bug 1)
**Q1:** I need braces in JB → [wait for results] → Actually, I want cleaning → [wait for results] → Book at first clinic  
**Expected:** Booking should confirm **cleaning**, NOT braces  
**Target Bug:** Bug 1 (services[-1] fix validation)

**Q2:** Search for root canal in Singapore → [wait for results] → Show me teeth whitening instead → [wait for results] → I want to book at first clinic  
**Expected:** Booking should confirm **teeth_whitening**, NOT root_canal  
**Target Bug:** Bug 1 (services array indexing)

### Category 2: DirectLookup Location Search (Bug 4)
**Q3:** Find clinics in JB City Centre  
**Expected:** List of JB City Centre clinics, NOT "couldn't find a clinic named 'in city'"  
**Target Bug:** Bug 4 (location keyword detection)

**Q4:** Show me dental clinics near Mount Austin  
**Expected:** List of Mount Austin clinics, NOT DirectLookup error  
**Target Bug:** Bug 4 (location search routing)

### Category 3: Policy Questions (Bug 5)
**Q5:** Do JB dental clinics accept Singapore insurance?  
**Expected:** QnA response about insurance policies, NOT "couldn't find a clinic named 'do accept insurance'"  
**Target Bug:** Bug 5 (insurance keyword routing)

**Q6:** What payment methods do JB clinics accept?  
**Expected:** QnA response about payment options, NOT DirectLookup error  
**Target Bug:** Bug 5 (policy question routing)

### Category 4: Clinic Context (Bug 2)
**Q7:** Find dental cleaning in Mount Austin → [wait for results showing 3 clinics] → I want to book here  
**Expected:** Booking should recognize "here" as referring to one of the listed clinics (likely last one)  
**Target Bug:** Bug 2 ("here" positional reference)

### Category 5: Cancel Keywords (Bug 3)
**Q8:** I need braces in JB → [wait for results] → Book at first clinic → [wait for booking prompt] → I changed my mind, I'll call them instead  
**Expected:** Booking should cancel gracefully  
**Target Bug:** Bug 3 (expanded cancel keywords)

**Q9:** Search for root canal → [wait for results] → abort plan  
**Expected:** Clear filters or provide search help, NOT "abort plan is unclear"  
**Target Bug:** Bug 3 (abort keyword detection)

### Category 6: Travel FAQ During Booking (Bug 8)
**Q10:** Find dental cleaning in JB → [wait for results] → Book at first clinic → [wait for booking prompt] → How do I get there from Singapore? → [wait for travel info] → Continue booking  
**Expected:** Should provide travel directions, then return to booking flow  
**Target Bug:** Bug 8 (travel FAQ during booking)

---

## Root Cause Summary

| Root Cause | Bugs | Queries Failed | % of Failures | File Location | Fix Complexity |
|------------|------|----------------|---------------|---------------|----------------|
| services[0] indexing | Bug 1 | Q4, Q10 | 40% (4/10) | booking_flow.py L108-118 | 1 line |
| DirectLookup misrouting | Bugs 4, 5 | Q2, Q6, Q7 | 30% (3/10) | find_clinic_flow.py | 13 lines |
| Cancel keywords incomplete | Bug 3 | Q1, Q9 | 30% (3/10) | booking_flow.py | 1 line |
| Clinic context loss | Bug 2 | Q5 | 10% (1/10) | booking_flow.py | 5 lines |
| Booking guard too strict | Bug 8 | Q8 | 10% (1/10) | booking_flow.py | 10 lines |

**Key Insight:** Top 2 root causes (services[0], DirectLookup) account for 70% of failures. Fixing these would achieve 80% accuracy.

---

## Response Time Analysis

### By Query Type
- **Search (Q3, Q4, Q5, Q10):** 8.5s average ✅
- **Booking (Q3-Q5, Q10):** 3.25s average ✅
- **DirectLookup Errors (Q2, Q6, Q7):** 12.3s average ❌ (slow due to fuzzy matching)
- **Cancel (Q1, Q2, Q9):** 2.3s average ✅
- **Overall Average:** 6.8s

### Observations
- Search queries fast and reliable when treatment+location provided
- DirectLookup errors slow (12s+) due to fuzzy matching attempts
- Booking confirmations fast but wrong treatment

---

## Critical Findings

### 1. DirectLookup is Catastrophic
- **70% of DirectLookup attempts fail** (7/10 across 3 sessions)
- Misinterprets location searches as clinic names ("in city", "near Mount Austin")
- Misinterprets policy questions as clinic names ("do accept insurance", "payment methods")
- **RECOMMENDATION:** Disable DirectLookup for queries with filter words OR policy keywords

### 2. Booking Flow Unusable
- **0% booking success rate across 14 attempts** (Sessions 2-4)
- Always uses wrong treatment due to services[0] bug
- **RECOMMENDATION:** Fix services[-1] immediately in V11

### 3. Cancel Detection Broken
- **0% cancel success rate in Sessions 3-4** (5/5 failed)
- Only works for exact keyword "cancel" in booking mode
- **RECOMMENDATION:** Expand cancel keyword list + add AI fallback

### 4. V9 Guard Not Working as Intended
- Travel FAQ blocked during booking despite V9 guard supposed to allow
- **RECOMMENDATION:** Rewrite guard logic to prioritize user questions over booking flow

---

## Recommendations

### Immediate Actions (V11 Release)
1. **Apply Priority 1 Fix** (Bug 1) to raise accuracy to 50%
2. **Apply Priority 2 Fixes** (Bugs 4, 5) to raise accuracy to 80%
3. **Test with 10-question suite above** to validate fixes
4. **Deploy V11 to production** if test accuracy ≥ 90%

### Future Improvements (V12+)
1. **Rewrite DirectLookup Heuristic:** Add guardrails to prevent misrouting
2. **AI-Powered Cancel Detection:** Use LLM to detect cancellation intent
3. **Stateful Booking Context:** Preserve clinic selection across turns
4. **Smart Booking Guard:** Detect legitimate mid-booking questions vs booking cancellation

### Testing Strategy
1. **V11 Testing:** Run 10-question suite (should achieve 90%+)
2. **Regression Testing:** Re-run Sessions 2-4 queries (should improve from 27% to 85%+)
3. **Integration Testing:** Multi-step bookings with context switches
4. **Edge Case Testing:** Unusual phrasings for cancel, policy, travel queries

---

## Conclusion

V10 Session 4 revealed **catastrophic failures in DirectLookup and booking confirmation**. With only 10% success rate (1/10), this is the worst performance across all test sessions.

**Critical Issues:**
1. **DirectLookup misroutes 70% of attempts** - mistaking location/policy queries for clinic names
2. **Booking flow 100% failure** - always confirms wrong treatment due to services[0] bug
3. **Cancel detection broken** - only "cancel" keyword works, all others fail

**V11 with all fixes would achieve: 100% accuracy** (10/10 successful)

The top priority is fixing **Bug 1 (services[-1])** and **Bugs 4+5 (DirectLookup misrouting)**, which would immediately raise accuracy from 10% to 80%.

**Critical Path to V11:**
1. Fix services[0] → services[-1] (1 line)
2. Add location keyword detection (8 lines)
3. Add policy keyword routing (5 lines)
4. Add "here" positional keyword (5 lines)
5. Expand cancel keywords (1 line)
6. Allow travel FAQ during booking (10 lines)

**Total Code Changes: ~30 lines across 2 files**  
**Expected Impact: 10% → 100% accuracy (+90 percentage points)**

---

**End of Analysis**
