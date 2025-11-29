# V10 Test Questions - Systematic Assessment

## Test Date: November 29, 2025
## Purpose: Validate V10 hotfix and probe identified bugs

---

## Category 1: Educational Queries (V10 Hotfix Validation)
**Target:** Verify ChatIntent.GENERAL_DENTAL_QUESTION fix works without crashes

### Q1: What is root canal treatment?
- **Expected:** Educational response about root canal procedure, no 500 error
- **Target Bug:** V10 hotfix (ChatIntent.QNA → GENERAL_DENTAL_QUESTION)
- **Success Criteria:** Response time <5s, no crash, accurate dental information

### Q2: How much does teeth whitening cost in Singapore?
- **Expected:** Educational response about whitening costs/procedures
- **Target Bug:** V10 hotfix validation
- **Success Criteria:** No crash, relevant cost information or "contact clinic" guidance

### Q3: What are the benefits of dental implants?
- **Expected:** Educational response about implant advantages
- **Target Bug:** V10 hotfix validation
- **Success Criteria:** Response time <5s, comprehensive benefits list

---

## Category 2: Treatment Context Preservation (Bug 1 - Critical)
**Target:** Verify if booking preserves LATEST treatment or still uses FIRST treatment

### Q4: I need root canal treatment in JB
[Wait for clinic results]
Then: Show me clinics for teeth whitening in JB instead
[Wait for new results]
Then: I want to book an appointment
- **Expected:** Booking should offer teeth_whitening (latest), NOT root_canal (first)
- **Target Bug:** Bug 1 - services[0] vs services[-1] array indexing
- **Success Criteria:** Booking context shows correct latest treatment
- **Critical Test:** This directly tests the V9 Fix 1 failure mode

### Q5: Find braces clinics in JB
[Wait for results]
Then: Actually, I want dental cleaning
[Wait for new results]  
Then: Book appointment at the first clinic
- **Expected:** Booking should confirm dental_cleaning, NOT braces
- **Target Bug:** Bug 1 - treatment array index bug
- **Success Criteria:** Confirmation message mentions correct treatment

---

## Category 3: Clinic Context Preservation (Bug 2 - Critical)
**Target:** Verify if clinic name persists after user views candidates

### Q6: Show me dental clinics in Mount Austin
[Note the first clinic name, e.g., "Mount Austin Dental Hub"]
Then: Tell me more about the first one
[Wait for details]
Then: I want to book
- **Expected:** Booking should remember clinic from "first one" reference
- **Target Bug:** Bug 2 - booking_context cleared, selected_clinic_name lost
- **Success Criteria:** No "No clinic name found" error

### Q7: Find root canal clinics in JB
[Note the third clinic name]
Then: What are the operating hours of the third clinic?
[Wait for response]
Then: I'd like to book an appointment there
- **Expected:** Booking should remember "third clinic" reference
- **Target Bug:** Bug 2 - positional reference not preserved
- **Success Criteria:** Booking proceeds with correct clinic name

---

## Category 4: Cancel Intent Detection (Bug 3)
**Target:** Verify natural language cancel variations are recognized

### Q8: I need braces in JB
[Wait for results]
Then: Show me the first clinic details
[Wait for details]
Then: I want to book
[Wait for booking prompt]
Then: I changed my mind
- **Expected:** Booking should cancel and offer to help differently
- **Target Bug:** Bug 3 - "changed my mind" not in cancel keywords
- **Success Criteria:** Graceful exit from booking, not "AI FALLBACK" error

### Q9: Find dental cleaning in Singapore
[Wait for results]
Then: Book at the second clinic
[Wait for booking prompt]
Then: Never mind, I'll call them instead
- **Expected:** Booking should recognize "never mind" and cancel
- **Target Bug:** Bug 3 - cancel keyword coverage incomplete
- **Success Criteria:** Polite acknowledgment of cancellation

---

## Category 5: Travel FAQ During Booking (Bug 4)
**Target:** Test if legitimate travel questions work during booking flow

### Q10: Show me clinics in Johor Bahru
[Wait for results]
Then: I want to book at Habib Dental
[Wait for booking prompt]
Then: How do I get there from Singapore?
- **Expected:** Should provide travel directions OR acknowledge and continue booking
- **Target Bug:** Bug 4 - booking guard blocks travel FAQ
- **Success Criteria:** Helpful response, not "AI FALLBACK" error
- **Design Question:** Should travel info be allowed mid-booking, or should it suggest "book first, then ask"?

---

## Category 6: Insurance/Policy Questions (Bug 5)
**Target:** Verify insurance queries route to QnA, not clinic search

### Q11: Do dental clinics in JB accept Singapore insurance?
- **Expected:** General policy information about insurance acceptance
- **Target Bug:** Bug 5 - "insurance" keyword misrouted to clinic search
- **Success Criteria:** QnA response, NOT clinic search for "do in accept insurance"

### Q12: What payment methods do JB clinics accept?
- **Expected:** General information about payment options
- **Target Bug:** Bug 5 - policy questions need better detection
- **Success Criteria:** Educational response, not clinic search

---

## Category 7: Multi-Step Booking Flow (Integration Test)
**Target:** End-to-end booking with context switches

### Q13: I want teeth whitening in Singapore
[Wait for results]
Then: Show me the cheapest option
[Wait for response]
Then: Actually, I prefer the second clinic
[Wait for acknowledgment]
Then: Book an appointment there for next Tuesday 3pm
[Wait for confirmation prompt]
Then: Confirm
- **Expected:** Complete booking with correct clinic and treatment throughout
- **Target Bugs:** Bug 1 (treatment), Bug 2 (clinic), integration stability
- **Success Criteria:** All context preserved, successful booking confirmation

---

## Category 8: Search Stability (Baseline Validation)
**Target:** Confirm search flow remains stable (was 100% in V10)

### Q14: Find affordable root canal clinics near JB City Centre
- **Expected:** Filtered results for root canal in JB, sorted by price/location
- **Target Bug:** None (baseline validation)
- **Success Criteria:** Response time <15s, relevant results, filters applied

---

## Category 9: Mixed Intent Edge Case
**Target:** Test ambiguous queries that could be search OR educational

### Q15: Tell me about dental clinics in Johor Bahru that do braces
- **Expected:** Either (A) clinic search results for braces in JB, OR (B) educational info about braces + offer to search
- **Target Bug:** None (ambiguity handling)
- **Success Criteria:** Reasonable interpretation, user can clarify if needed, no crash

---

## Testing Protocol

### Execution Order:
1. **Phase 1 (Q1-Q3):** Validate V10 hotfix works - MUST pass all 3
2. **Phase 2 (Q4-Q5):** Test treatment bug - expect FAILURE in V10
3. **Phase 3 (Q6-Q7):** Test clinic bug - expect FAILURE in V10  
4. **Phase 4 (Q8-Q9):** Test cancel detection - expect PARTIAL failure
5. **Phase 5 (Q10):** Test travel FAQ guard - expect FAILURE
6. **Phase 6 (Q11-Q12):** Test insurance routing - expect FAILURE on Q11
7. **Phase 7 (Q13):** Integration test - expect FAILURE due to Bug 1+2
8. **Phase 8 (Q14-Q15):** Baseline validation - expect SUCCESS

### Success Metrics:
- **V10 Hotfix Validation:** 3/3 educational queries pass (100%)
- **Known Bugs:** 5/7 bug-targeted tests fail as documented (71% failure expected)
- **Baseline Stability:** 2/2 search/edge cases pass (100%)
- **Overall V10 Expected:** 5-6/15 pass (33-40%) - confirms bugs exist
- **V11 Target:** 13-14/15 pass (87-93%) after fixing Bug 1+2

### Logging Requirements:
- Record response time for every query
- Capture booking_context state before/after each request
- Note applied_filters.services array evolution
- Screenshot Render logs for intent classification
- Track session_id consistency across conversation

### Pass/Fail Criteria Per Question:

| Question | Pass Criteria | Fail Indicators |
|----------|---------------|-----------------|
| Q1-Q3 | Educational response, no crash, <5s | 500 error, wrong intent, >10s |
| Q4-Q5 | Booking shows LATEST treatment | Booking shows FIRST treatment searched |
| Q6-Q7 | Booking remembers clinic from position | "No clinic name found" error |
| Q8-Q9 | Cancel acknowledged gracefully | "AI FALLBACK" error, booking continues |
| Q10 | Travel directions OR polite defer | "AI FALLBACK" error, crash |
| Q11-Q12 | QnA response about policy | Clinic search with mangled query |
| Q13 | Complete booking, all context correct | Any context loss at any step |
| Q14 | Filtered search results | Wrong filters, no results, crash |
| Q15 | Reasonable interpretation | Crash, nonsense response |

---

## Expected V10 Results (Based on Previous Testing)

### Will PASS:
- Q1, Q2, Q3 (educational - hotfix works)
- Q14 (search baseline - stable)
- Q15 (edge case - tolerant)
- **Expected Pass Rate: 5/15 (33%)**

### Will FAIL:
- Q4, Q5 (treatment bug - services[0] issue)
- Q6, Q7 (clinic bug - context clearing)
- Q8 (cancel - "changed my mind" not recognized)
- Q9 (cancel - "never mind" might work, 50/50)
- Q10 (travel FAQ - booking guard blocks)
- Q11 (insurance - wrong routing)
- Q13 (integration - multiple bugs compound)
- **Expected Fail Rate: 9-10/15 (60-67%)**

---

## V11 Predictions (After Bug 1+2 Fixes)

### Will PASS (13-14/15):
- Q1-Q3 (educational - already fixed)
- Q4-Q5 (treatment - services[-1] fix)
- Q6-Q7 (clinic - context preservation fix)
- Q13 (integration - Bug 1+2 fixed)
- Q14-Q15 (baseline - stable)
- Q9 (cancel - if "never mind" added to keywords)
- **Expected Pass Rate: 13-14/15 (87-93%)**

### May Still FAIL (1-2/15):
- Q8 (cancel - needs "changed my mind" keyword)
- Q10 (travel FAQ - guard too strict)
- Q11 (insurance - needs routing improvement)
