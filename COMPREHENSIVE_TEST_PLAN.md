# SG-JB Dental Chatbot - Comprehensive Test Plan
## Pre-Launch Testing Guide

---

## 🤖 AI CAPABILITIES INVENTORY

### **1. FIND_CLINIC FLOW**
**AI Models Used:**
- Gemini 2.5 Pro (Factual Brain) - Entity extraction
- Gemini 2.5 Pro (Ranking Brain) - Clinic ranking
- Gemini 2.5 Flash (Generation) - Response formatting

**Capabilities:**
1. **Service Extraction** - Identifies dental services from natural language
2. **Township/Location Extraction** - Extracts specific areas within SG/JB
3. **Direct Clinic Name Lookup** - Fuzzy matching for specific clinic queries
4. **Multi-Service Stacking** - Accumulates multiple services across conversation
5. **Quality Gate Filtering** - Filters clinics by rating (≥4.5) and reviews (≥30)
6. **Ranking by Rating & Reviews** - Sorts clinics by quality metrics
7. **Location Preference Memory** - Remembers user's country choice (SG/JB/Both)
8. **Location Change Detection** - Detects when user wants to switch countries
9. **Township-Country Mapping** - Infers country from specific areas (e.g., "Taman Molek" → JB)
10. **Cost Comparison** - Provides SG vs JB price ranges for procedures
11. **Metro JB Filter** - Special filter for easily accessible JB clinics

---

### **2. TRAVEL_FAQ FLOW** 
**AI Models Used:**
- text-embedding-004 - Semantic search embeddings
- Gemini 2.5 Pro (Generation) - FAQ answer generation

**Capabilities:**
1. **Semantic FAQ Search** - Embedding-based travel question matching (threshold 0.5)
2. **General Travel Directions** - Provides SG-to-JB travel info (bus, train, taxi, checkpoint)
3. **Clinic-Specific Travel** - Interprets clinic names/ordinals as general travel queries
4. **Travel Guard** - Filters out trivial location tokens
5. **URL Extraction** - Extracts and returns relevant travel resource links

---

### **3. QNA FLOW**
**AI Models Used:**
- Gemini 2.5 Flash (Generation) - Educational response generation

**Capabilities:**
1. **General Dental Education** - Answers "what is", "how does", "tell me about" queries
2. **Disclaimer Injection** - Auto-appends medical disclaimer to all responses
3. **Follow-up Guidance** - Suggests finding clinics related to the topic
4. **State Preservation** - Maintains candidate pool and filters through educational queries

---

### **4. BOOKING FLOW**
**AI Models Used:**
- Gemini 2.5 Pro (Factual Brain) - Clinic name extraction, user info extraction
- Gemini 2.5 Flash (Booking Model) - Confirmation handling

**Capabilities:**
1. **Ordinal Clinic Selection** - "Book at first clinic" references
2. **Clinic Name Extraction** - Extracts clinic from natural language
3. **Treatment Inference** - Uses previous service filters as booking treatment
4. **3-Stage Booking**:
   - Stage 1: Identify clinic
   - Stage 2: Confirm details (deterministic yes/no + AI fallback)
   - Stage 3: Capture user info (name, email, WhatsApp)
5. **Correction Handling** - Allows users to change clinic/treatment mid-flow
6. **Pre-filled Form Generation** - Creates booking URL with query parameters
7. **Deterministic Confirmation** - Uses keyword matching for "yes"/"no" before AI

---

### **5. REMEMBER_SESSION FLOW**
**AI Models Used:**
- None (rule-based session retrieval)

**Capabilities:**
1. **Clinic Recall** - Retrieves previously recommended clinics
2. **Filter Recall** - Shows what filters were applied
3. **Booking Context Recall** - Retrieves incomplete booking details
4. **Conversation History** - (Placeholder - not fully implemented)

---

### **6. OUT_OF_SCOPE FLOW**
**AI Models Used:**
- None (keyword-based routing)

**Capabilities:**
1. **Greeting Detection** - Responds to "hello", "hi", "how are you"
2. **Weather Redirect** - Detects weather queries and redirects
3. **Generic Rejection** - Handles all other non-dental topics

---

### **7. ROUTING & INTENT CLASSIFICATION**
**AI Models Used:**
- Gemini 2.5 Pro (Gatekeeper) - Intent classification with confidence scoring

**7-Phase Routing Priority:**
1. **Travel Intent Detection** - Checks for "how to get", "directions", etc.
2. **Ordinal Pattern Matching** - Regex for "first/second/third clinic"
3. **Booking Signal Detection** - "book", "schedule", "appointment" + clinic reference
4. **Active Booking Status** - Continues booking conversation if in progress
5. **Gatekeeper AI** - LLM-based intent classification (confidence ≥0.7)
6. **Heuristics Safety Net**:
   - Travel keywords → TRAVEL_FAQ
   - Educational patterns → QNA
   - Search/service keywords → FIND_CLINIC
7. **Semantic Travel Check** - Embedding-based travel FAQ matching

**Special Routing Features:**
- **Travel Priority Over Ordinal** - "How to get to first clinic" → Travel (not clinic card)
- **Educational Priority Over Service** - "Tell me about root canal" → QNA (not search)
- **Ordinal Fallback** - Returns first clinic if pattern matches but resolver fails

---

### **8. STATE MANAGEMENT**
**Session State Fields:**
- `applied_filters` - Current search criteria
- `candidate_pool` - List of recommended clinics
- `booking_context` - Booking progress (status, clinic_name, treatment)
- `location_preference` - User's country choice (sg/jb/all)
- `awaiting_location` - Flag for location prompt state
- `selected_clinic_id` - ID of clinic user clicked on

**State Preservation:**
- Spread operator pattern: `{**state, ...new_values}`
- Explicit preservation in travel/QnA flows
- Booking completion clears booking_context but preserves filters/clinics

---

## 📋 COMPREHENSIVE TEST QUERIES

### **CATEGORY 1: FIND_CLINIC TESTS**

#### **1.1 Basic Service Search**
```
Query: ""Find clinics for scaling
Expected: Prompt for location (SG/JB/Both) if no preference set
Test: Verify location prompt appears with 3 buttons
```

```
Query: "Best clinics for root canal in JB"
Expected: 3 JB clinics with root_canal=True, sorted by rating/reviews
Test: All 3 clinics have rating ≥4.5, reviews ≥30, country=MY
```

```
Query: "I need teeth whitening in Singapore"
Expected: 3 SG clinics with teeth_whitening=True
Test: All clinics have country=SG, location context message shows "Showing clinics in Singapore..."
```

#### **1.2 Direct Clinic Name Lookup**
```
Query: "Tell me about Aura Dental Adda Heights"
Expected: Single clinic detail card with address, rating, hours
Test: Returns only Aura Dental, no list of 3 clinics
```

```
Query: "Q&M dental"
Expected: Finds Q & M brand clinics (handles "&" variations)
Test: Fuzzy matching works for brand names
```

```
Query: "Show me Koh Dental" (typo test)
Expected: Typo correction finds "Koh Dental" clinics
Test: Verifies typo_corrections dict working
```

#### **1.3 Township/Area Filtering**
```
Query: "Dental clinics in Taman Molek"
Expected: JB clinics in Taman Molek area (auto-infers JB)
Test: location_preference set to 'jb', township filter applied
```

```
Query: "Find dentist near Jurong"
Expected: SG clinics in Jurong (auto-infers SG)
Test: location_preference set to 'sg', township filter applied
```

```
Query: "Clinics in Mount Austin for braces"
Expected: JB clinics with braces=True in Mount Austin
Test: Both township and service filters applied correctly
```

#### **1.4 Multi-Service Stacking**
```
Session Flow:
1. "Find clinics for scaling in JB"
2. "Also show root canal"
Expected: Second query ADDS root canal without removing scaling
Test: applied_filters shows ['scaling', 'root_canal']
```

#### **1.5 Location Change Detection**
```
Session Flow:
1. "Best clinics for scaling" → User selects "JB"
2. Bot returns 3 JB clinics
3. "Show me Singapore clinics instead"
Expected: Bot switches to SG, returns 3 SG clinics
Test: Verify location_preference changes from 'jb' to 'sg', new results shown
```

```
Query: "I want to see JB clinics rather than SG"
Expected: Bot detects "rather than" trigger, switches location
Test: location_change_triggers array working
```

#### **1.6 Location Context Display**
```
Query: "Best clinics for dental crown"
Expected: After location selected, response includes "_Showing clinics in [country]. Want to see [other country] instead?_"
Test: Verify location_context message appended to response
```

#### **1.7 Cost Comparison**
```
Query: "How much does root canal cost in SG vs JB?"
Expected: Structured comparison with price ranges:
- SG: 800-1500
- JB: 200-400
Test: No clinic list, just price comparison data
```

```
Query: "Compare dental implant prices"
Expected: SG vs JB price ranges for implants
Test: procedures_reference lookup working
```

#### **1.8 Metro JB Filter**
```
Query: "Easy to reach clinics in JB"
Expected: Only clinics with is_metro_jb=True
Test: Filters to metro-accessible JB clinics
```

---

### **CATEGORY 2: ORDINAL REFERENCE TESTS**

#### **2.1 Basic Ordinal Selection**
```
Session Flow:
1. "Best clinics for scaling in JB" → Returns 3 clinics
2. "Show me the first clinic"
Expected: Single clinic detail card for candidate_clinics[0]
Test: selected_clinic_id set, full detail card displayed
```

```
Session Flow:
1. Previous search returns 3 clinics
2. "Tell me about the second one"
Expected: Detail card for candidate_clinics[1]
Test: Ordinal resolver extracts "second" correctly
```

```
Session Flow:
1. Previous search returns 3 clinics
2. "What about #3?"
Expected: Detail card for candidate_clinics[2]
Test: Regex matches "#3" pattern
```

#### **2.2 Ordinal Fallback**
```
Session Flow:
1. Previous search returns 3 clinics
2. "Show the first clinic from the list"
Expected: Detail card for first clinic (fallback triggers)
Test: Pattern matches but resolve fails → returns candidate_clinics[0]
```

#### **2.3 Ordinal Without Candidate Pool**
```
Query: "Show me the first clinic"
Expected: "I don't have a clinic list ready. Which country would you like to explore?"
Test: Prompts for location when no candidate_pool exists
```

---

### **CATEGORY 3: TRAVEL_FAQ TESTS**

#### **3.1 General Travel Queries**
```
Query: "How do I get from Singapore to Johor Bahru?"
Expected: General SG-to-JB directions (bus, train, checkpoint info)
Test: Semantic search finds relevant FAQ, Gemini generates answer
```

```
Query: "What bus can I take to JB?"
Expected: Bus route information (CW1, CW2, etc.)
Test: Travel keywords detected, semantic search engaged
```

```
Query: "Checkpoint procedures for entering JB"
Expected: Immigration/customs process explanation
Test: FAQ matching and generation working
```

#### **3.2 Clinic-Specific Travel (with Ordinal)**
```
Session Flow:
1. "Best clinics for scaling in JB" → Returns 3 clinics
2. "How to get to the first clinic from Singapore by public transport?"
Expected: General SG-to-JB travel directions (NOT clinic detail card)
Test: Travel intent detected BEFORE ordinal → routes to TRAVEL_FAQ
```

```
Session Flow:
1. Previous search returns 3 clinics (Aura Dental, Mount Austin, etc.)
2. "Directions to Aura Dental from SG?"
Expected: General SG-to-JB travel info
Test: Special instructions in prompt interpret clinic name as general travel query
```

#### **3.3 Travel Guard Tests**
```
Query: "Singapore"
Expected: None (travel flow skips trivial location token)
Test: Verify travel_flow.py returns None for single-word countries
```

```
Query: "JB"
Expected: None (too short, no travel keywords)
Test: Guard requires 3+ tokens OR clear travel keyword
```

---

### **CATEGORY 4: QNA TESTS**

#### **4.1 Educational Questions**
```
Query: "What is a root canal?"
Expected: Educational explanation + disclaimer + follow-up question
Test: Routes to QNA (not FIND_CLINIC), disclaimer appended
```

```
Query: "Tell me more about dental implants"
Expected: Implant procedure explanation + disclaimer
Test: "Tell me more" pattern detected BEFORE service keyword
```

```
Query: "How does teeth whitening work?"
Expected: Whitening process explanation + disclaimer
Test: Educational pattern prioritized over service search
```

```
Query: "Is it painful to get braces?"
Expected: Braces pain/discomfort explanation + disclaimer
Test: Question pattern recognized
```

#### **4.2 State Preservation in QNA**
```
Session Flow:
1. "Best clinics for scaling in JB" → Returns 3 clinics
2. "What is scaling?"
Expected: Educational response + candidate_pool STILL contains 3 clinics
Test: State preserved through QNA flow
```

#### **4.3 Follow-up Guidance**
```
Query: "Tell me about wisdom tooth extraction"
Expected: Response ends with "Would you like me to help you find a clinic that can assist with this?"
Test: Follow-up question appended after disclaimer
```

---

### **CATEGORY 5: BOOKING FLOW TESTS**

#### **5.1 Basic Booking with Ordinal**
```
Session Flow:
1. "Best clinics for root canal in JB" → Returns 3 clinics
2. "Book appointment at first clinic"
Expected: "Just to confirm, are you looking to book for root_canal at [Clinic Name]?"
Test: booking_context.status = 'confirming_details'
```

#### **5.2 Booking with Specific Clinic Name**
```
Query: "I want to book at Aura Dental for scaling"
Expected: Confirmation prompt with Aura Dental
Test: Clinic name extracted from text
```

#### **5.3 Confirmation Flow**
```
Session Flow:
1. Booking confirmation prompt appears
2. User: "yes"
Expected: "What is your full name, email address, and WhatsApp number?"
Test: Deterministic "yes" detection, status → 'gathering_info'
```

```
Session Flow:
1. Booking confirmation prompt appears
2. User: "no, wrong clinic"
Expected: "Let's start over. What can I help you with?"
Test: Deterministic "no" detection, booking_context cleared
```

#### **5.4 Correction Handling**
```
Session Flow:
1. Booking confirmation: "Book for root_canal at Clinic A?"
2. User: "Actually, I want scaling instead"
Expected: "So that's scaling at Clinic A. Is that correct?"
Test: AI extracts corrected_treatment, updates booking_context
```

#### **5.5 User Info Capture**
```
Session Flow:
1. Status = 'gathering_info'
2. User: "John Doe, john@email.com, +6512345678"
Expected: Pre-filled booking URL with encoded parameters
Test: UserInfo extraction, URL generation with urlencode
```

#### **5.6 Direct Info Provision (Skip Confirmation)**
```
Session Flow:
1. Booking confirmation prompt appears
2. User: "My name is Jane, email jane@test.com, phone 87654321"
Expected: Bot detects has_info=true, captures details directly
Test: Pre-check prompt detects personal info, skips confirmation
```

---

### **CATEGORY 6: REMEMBER_SESSION TESTS**

#### **6.1 Clinic Recall**
```
Session Flow:
1. "Best clinics for scaling in JB" → Returns 3 clinics
2. "What clinics did you recommend?"
Expected: List of 3 clinics with full details
Test: Retrieves candidate_pool from session state
```

```
Query: "Remind me of the clinics you showed"
Expected: Previous clinic recommendations displayed
Test: Remember flow triggered
```

#### **6.2 Booking Recall**
```
Session Flow:
1. User started booking but didn't complete
2. "What was I booking?"
Expected: Shows selected_clinic, treatment, any collected info
Test: Retrieves booking_context from session
```

#### **6.3 No Session Data**
```
Query: "What clinics did we discuss?"
Expected: "I don't have any previous conversation history to recall."
Test: Handles empty session gracefully
```

---

### **CATEGORY 7: OUT_OF_SCOPE TESTS**

#### **7.1 Greeting Handling**
```
Query: "Hello!"
Expected: "Hello! I'm an AI assistant ready to help you with your dental clinic search."
Test: Greeting keyword detection
```

```
Query: "How are you?"
Expected: Friendly greeting response
Test: Greeting variant handling
```

#### **7.2 Weather Queries**
```
Query: "What's the weather in Singapore?"
Expected: "I am not able to provide weather forecasts..."
Test: Weather keyword detection
```

#### **7.3 Generic Out-of-Scope**
```
Query: "Tell me a joke"
Expected: "I am an AI Concierge designed to help with dental clinic information..."
Test: Default rejection for non-dental topics
```

---

### **CATEGORY 8: ROUTING PRIORITY TESTS**

#### **8.1 Travel Priority Over Ordinal**
```
Session Flow:
1. Search returns 3 clinics
2. "How to get to first clinic by bus?"
Expected: Routes to TRAVEL_FAQ (not clinic detail card)
Test: has_travel_intent=True bypasses ordinal check
```

#### **8.2 Educational Priority Over Service**
```
Query: "Tell me about root canal treatment"
Expected: Routes to QNA (not FIND_CLINIC)
Test: Educational pattern detected before service keyword
```

#### **8.3 Booking During Active Booking**
```
Session Flow:
1. booking_context.status = 'confirming_details'
2. User: "yes"
Expected: Routes to BOOKING_FLOW (not gatekeeper)
Test: Active booking status overrides other routing
```

#### **8.4 Heuristics Fallback**
```
Query: "Scaling clinics" (Gatekeeper returns intent=None)
Expected: Heuristics detects service keyword → FIND_CLINIC
Test: Safety net catches when Gatekeeper fails
```

---

### **CATEGORY 9: EDGE CASE TESTS**

#### **9.1 Empty/Minimal Input**
```
Query: ""
Expected: Graceful handling, no crash
Test: Guards in place for empty strings
```

```
Query: "JB"
Expected: Location capture if awaiting_location, else gentle prompt
Test: Single-word handling
```

#### **9.2 Mixed Intent Queries**
```
Query: "Book appointment for root canal and tell me what root canal is"
Expected: Prioritizes booking intent
Test: Routing handles multiple intents
```

#### **9.3 Typos and Variations**
```
Query: "dentil implnt" (typos)
Expected: Fuzzy matching/normalization handles typos
Test: Service extraction robust to misspellings
```

```
Query: "Q and M dental" vs "Q&M dental" vs "Q & M dental"
Expected: All variants match same brand
Test: Brand pattern normalization working
```

#### **9.4 Very Long Queries**
```
Query: "I'm looking for a dental clinic in Johor Bahru that offers high-quality scaling and cleaning services, preferably one that's highly rated and has a lot of positive reviews from Singaporean patients who have visited before"
Expected: Extracts key info: service=scaling, location=JB
Test: AI handles verbose input gracefully
```

#### **9.5 Multiple Sessions/Users**
```
Test: Two users searching simultaneously
Expected: Session isolation works, no cross-contamination
Test: session_id properly isolates state
```

---

### **CATEGORY 10: STATE MANAGEMENT TESTS**

#### **10.1 State Preservation Across Flows**
```
Session Flow:
1. "Find scaling clinics in JB" → 3 clinics stored
2. "What is scaling?" (QNA flow)
3. "Show me the first clinic" (Ordinal reference)
Expected: Ordinal still works after QNA (candidate_pool preserved)
Test: State preserved through flow transitions
```

#### **10.2 Booking Completion Clears Context**
```
Session Flow:
1. Complete booking → booking_context.status = 'complete'
2. Next query
Expected: booking_context cleared, but filters/clinics preserved
Test: Selective state clearing working
```

#### **10.3 Reset Functionality**
```
Query: "reset"
Expected: All state cleared, location prompt appears
Test: hard_reset_active flag works
```

---

## 🎯 CRITICAL PATH TESTS (Must Pass Before Launch)

### **Priority 1: Core User Journey**
1. ✅ **Search Flow**: "Find root canal clinics in JB" → 3 clinics returned
2. ✅ **Location Context**: Response shows "Showing clinics in Johor Bahru..."
3. ✅ **Ordinal Selection**: "Show first clinic" → Detail card displayed
4. ✅ **Travel Query**: "How to get there from Singapore?" → Travel directions (not clinic card)
5. ✅ **Booking Initiation**: "Book here" → Confirmation prompt
6. ✅ **Booking Completion**: Provide info → Booking URL generated

### **Priority 2: UX Quality**
1. ✅ **Location Change**: "Switch to Singapore" → Results update
2. ✅ **Educational Queries**: "Tell me about root canal" → QNA response + state preserved
3. ✅ **Cost Comparison**: "How much does it cost?" → Price ranges shown
4. ✅ **Session Recall**: "What clinics did you show me?" → Previous results retrieved

### **Priority 3: Error Handling**
1. ✅ **No Results**: Search with no matches → Helpful message
2. ✅ **Invalid Ordinal**: "Show 10th clinic" (only 3 exist) → Graceful handling
3. ✅ **Booking Without Clinics**: "Book appointment" (no search yet) → Prompts for clinic
4. ✅ **Out-of-Scope**: "Tell me a joke" → Polite rejection

---

## 📊 TEST EXECUTION CHECKLIST

### **Pre-Test Setup**
- [ ] Verify Render deployment is live
- [ ] Check Supabase connection (clinics_data, sg_clinics tables populated)
- [ ] Verify travel FAQ embeddings indexed
- [ ] Confirm GEMINI_API_KEY active
- [ ] Clear test session data

### **During Testing**
- [ ] Test each category sequentially
- [ ] Record Render logs for failed tests
- [ ] Note console output for debugging
- [ ] Track candidate_pool state across queries
- [ ] Verify location_preference updates

### **Success Criteria**
- [ ] All Priority 1 tests pass (100%)
- [ ] ≥90% of Priority 2 tests pass
- [ ] ≥80% of Priority 3 tests pass
- [ ] No critical errors in Render logs
- [ ] State preservation working across all flows

---

## 🐛 KNOWN ISSUES TO MONITOR

1. **Gatekeeper Unreliability**: Frequently returns `intent=None, conf=0.00` → Heuristics must be robust
2. **DirectLookup Overfiring**: May trigger on educational queries mentioning clinic names → Monitor logs
3. **Ordinal Resolver Strictness**: Fails on queries with extra words → Fallback logic added
4. **Location Memory Persistence**: May confuse users who want to explore both countries → Context message added

---

## 📝 TEST REPORTING FORMAT

For each failed test, document:
```
Test ID: [Category].[Number]
Query: "[Exact user input]"
Expected: [Expected behavior]
Actual: [What actually happened]
Render Log Trace ID: [trace_id from logs]
Console Output: [Relevant console messages]
Root Cause: [Analysis of why it failed]
Fix Needed: [Proposed solution]
```

---

## 🚀 LAUNCH READINESS CRITERIA

✅ **Green Light Conditions:**
- All Priority 1 tests passing
- No critical routing failures
- State management working consistently
- Booking flow end-to-end functional
- Travel FAQ returning relevant results

🟡 **Yellow Light (Launch with Monitoring):**
- Priority 2 tests ≥85% pass rate
- Minor UX issues (can be iterated)
- Gatekeeper inconsistency (heuristics compensate)

🔴 **Red Light (Do Not Launch):**
- Any Priority 1 test failing
- State loss/corruption issues
- Booking flow broken
- Repeated crashes/errors

---

## 🎯 QUICK LAUNCH TEST (15 Essential Queries)
**Time Required:** 20-30 minutes  
**Coverage:** All 8 major flows tested

### **Test Sequence (Copy-paste each query)**

#### **1. FIND_CLINIC FLOW (3 tests)**
```
Query 1: "Find clinics for root canal in JB"
✅ Expected: Prompt for location OR 3 JB clinics if location remembered
✅ Check: Location context message appears ("Showing clinics in Johor Bahru...")
```

```
Query 2: "Best clinics for scaling in Singapore"
✅ Expected: 3 SG clinics, rating ≥4.5, reviews ≥30
✅ Check: Location context shows "Showing clinics in Singapore. Want to see JB clinics instead?"
```

```
Query 3: "Show me JB clinics instead"
✅ Expected: Location switches from SG to JB, new 3 clinics displayed
✅ Check: location_preference changes, results update correctly
```

---

#### **2. ORDINAL REFERENCE (2 tests)**
```
Query 4: "Tell me about the first clinic"
✅ Expected: Single clinic detail card with address, rating, hours
✅ Check: selected_clinic_id set, NOT a list of 3 clinics
```

```
Query 5: "What about the second one?"
✅ Expected: Detail card for second clinic from previous list
✅ Check: Ordinal resolver works for "second"
```

---

#### **3. TRAVEL_FAQ (2 tests)**
```
Query 6: "How do I get from Singapore to JB?"
✅ Expected: General travel directions (bus, train, checkpoint info)
✅ Check: Semantic FAQ search finds match, generates answer
```

```
Query 7: "How to get to the first clinic by public transport?"
✅ Expected: General SG-to-JB travel directions (NOT clinic detail card)
✅ Check: Travel intent detected BEFORE ordinal → routes to TRAVEL_FAQ
```

---

#### **4. QNA FLOW (2 tests)**
```
Query 8: "What is a root canal?"
✅ Expected: Educational explanation + disclaimer + follow-up question
✅ Check: Routes to QNA (not FIND_CLINIC), disclaimer present
```

```
Query 9: "Tell me more about dental implants"
✅ Expected: Implant explanation + disclaimer + candidate_pool PRESERVED
✅ Check: Educational pattern prioritized, state not cleared
```

---

#### **5. BOOKING FLOW (3 tests)**
```
Query 10: "Book appointment at first clinic"
✅ Expected: "Just to confirm, are you looking to book for [service] at [clinic]?"
✅ Check: booking_context.status = 'confirming_details'
```

```
Query 11: "yes"
✅ Expected: "What is your full name, email address, and WhatsApp number?"
✅ Check: Deterministic "yes" detection, status → 'gathering_info'
```

```
Query 12: "John Doe, john@test.com, +6512345678"
✅ Expected: Pre-filled booking URL generated
✅ Check: UserInfo extraction works, URL contains encoded parameters
```

---

#### **6. REMEMBER_SESSION (1 test)**
```
Query 13: "What clinics did you recommend earlier?"
✅ Expected: List of previously shown clinics retrieved
✅ Check: Retrieves candidate_pool from session state
```

---

#### **7. OUT_OF_SCOPE (1 test)**
```
Query 14: "Tell me a joke"
✅ Expected: "I am an AI Concierge designed to help with dental clinic information..."
✅ Check: Polite rejection, doesn't crash
```

---

#### **8. ROUTING PRIORITY (1 test)**
```
Query 15: "Tell me about root canal treatment options"
✅ Expected: Routes to QNA (not FIND_CLINIC search)
✅ Check: Educational pattern detected BEFORE service keyword "root canal"
```

---

### **✅ PASS CRITERIA**
- **Must Pass:** 13/15 tests (87% success rate)
- **Critical Failures:** Any of tests 1-4, 6-7, 10-12 fail
- **Launch Decision:**
  - 15/15 = 🟢 **Green Light** - Launch immediately
  - 13-14/15 = 🟡 **Yellow Light** - Launch with monitoring
  - <13/15 = 🔴 **Red Light** - Debug before launch

---

### **📝 QUICK TEST TRACKING SHEET**

| # | Test | Pass/Fail | Notes |
|---|------|-----------|-------|
| 1 | Find JB root canal | ⬜ | |
| 2 | Find SG scaling + context | ⬜ | |
| 3 | Switch to JB | ⬜ | |
| 4 | First clinic detail | ⬜ | |
| 5 | Second clinic detail | ⬜ | |
| 6 | General travel directions | ⬜ | |
| 7 | Travel to first clinic | ⬜ | |
| 8 | What is root canal | ⬜ | |
| 9 | Tell me about implants | ⬜ | |
| 10 | Book at first clinic | ⬜ | |
| 11 | Confirm "yes" | ⬜ | |
| 12 | Provide user info | ⬜ | |
| 13 | Recall clinics | ⬜ | |
| 14 | Out of scope | ⬜ | |
| 15 | Educational routing | ⬜ | |

**Total Passed:** ___/15

---

**Document Version:** 1.0  
**Last Updated:** November 27, 2025  
**Test Coverage:** 60+ test scenarios across 10 categories  
**Quick Launch Test:** 15 essential queries, 20-30 minutes  
**Full Test Suite:** 2-3 hours
