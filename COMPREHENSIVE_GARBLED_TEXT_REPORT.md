# COMPREHENSIVE GARBLED TEXT ANALYSIS FOR faqs_semantic TABLE
**Database:** Supabase faqs_semantic
**Total FAQs Analyzed:** 102
**FAQs with Garbling Issues:** 54
**Total Garbled Characters:** 141

---

## SUMMARY OF HEX CODES FOUND

| Hex Code | Character | Count | Should Be | Pattern Type |
|----------|-----------|-------|-----------|--------------|
| 0x80 | (control) | 67 | — (em-dash) | En-dash/Em-dash for ranges and punctuation |
| 0x94 | (control) | 33 | " (right double quote) | Closing quote or separator |
| 0x93 | (control) | 21 | " (left double quote) | Opening quote or separator |
| 0x99 | (control) | 9 | ' (apostrophe) | Apostrophe in contractions (can't, I'm, what's, clinic's) |
| 0x91 | (control) | 4 | ' (left single quote) | Apostrophe or opening single quote |
| 0x86 | (control) | 3 | → (arrow) | Directional arrow (Singapore → JB) |
| 0x92 | (control) | 3 | ' (right single quote) | Closing single quote or apostrophe |
| 0x97 | (control) | 1 | — (em-dash) | Em-dash |

---

## PATTERN ANALYSIS

### Pattern 1: Missing Spaces + Em-dash (Most Common)
**Example:** `Yescan` → `Yes—can` or `Yes; can`
**Occurrences:** 30+ instances
**Context:** Answer starts (Yes/No/Often) immediately followed by explanation

### Pattern 2: Time Range Dashes
**Example:** `7â9:30` → `7AM–9:30AM` or `7–9:30`
**Context:** Time ranges in answers about timing

### Pattern 3: Missing Apostrophes in Contractions
**Example:** 
- `Im` → `I'm`
- `whats` → `what's`
- `cant` → `can't`
- `ân` → `'n` (as in "Touch 'n Go")

### Pattern 4: Missing Possessive Apostrophes
**Example:**
- `dentists specific` → `dentist's specific`
- `clinics address` → `clinic's address`

### Pattern 5: Missing Hyphens in Compound Words
**Example:**
- `offpeak` → `off-peak`
- `inperson` → `in-person`
- `welllit` → `well-lit`
- `SGfocused` → `SG-focused`

### Pattern 6: Wrong Multiplication Symbol
**Example:** `Ã` → `×` (times symbol)
**Context:** "10–20× bus price"

### Pattern 7: Directional Arrow
**Example:** `Singapore â JB` → `Singapore → JB`

---

## DETAILED CORRECTIONS NEEDED (BY FAQ ID)

### ID 4 | Category: preparation | Field: answer
**Current:** `Yescan avoid repeat imaging and save time.`
**Corrected:** `Yes; can avoid repeat imaging and save time.`
**Issues:** Missing space and punctuation after "Yes"

---

### ID 8 | Category: preparation | Field: answer
**Current:** `Nopersonal care items like whitening gel are fine.`
**Corrected:** `No; personal care items like whitening gel are fine.`
**Issues:** Missing space and punctuation after "No"

---

### ID 9 | Category: timing | Field: answer
**Current:** `Weekday AM (7â9:30 SGJB) and PM (5â8 JBSG); early weekend mornings too.`
**Corrected:** `Weekday AM (7AM–9:30AM SG→JB) and PM (5PM–8PM JB→SG); early weekend mornings too.`
**Issues:** 
- Time ranges need proper dashes (–)
- Missing AM/PM indicators
- Arrow symbol for direction

---

### ID 10 | Category: timing | Field: answer
**Current:** `Mid-morning (10â3) or late night after 9 PM.`
**Corrected:** `Mid-morning (10AM–3PM) or late night after 9 PM.`
**Issues:** Time range with wrong dash, missing AM/PM

---

### ID 12 | Category: timing | Field: answer
**Current:** `Yesoften 1â2 hour queues back to SG.`
**Corrected:** `Yes; often 1–2 hour queues back to SG.`
**Issues:** Missing space/punctuation, wrong dash in range

---

### ID 13 | Category: timing | Field: answer
**Current:** `Yesmore family travel and longer car lines.`
**Corrected:** `Yes; more family travel and longer car lines.`
**Issues:** Missing space and punctuation

---

### ID 14 | Category: timing | Field: answer
**Current:** `Often yesslower driving and cautious queues.`
**Corrected:** `Often yes; slower driving and cautious queues.`
**Issues:** Missing space and punctuation

---

### ID 18 | Category: crossing_process | Field: answer
**Current:** `Possible but noisy & exposedbus or vehicle easier.`
**Corrected:** `Possible but noisy & exposed; bus or vehicle easier.`
**Issues:** Missing space and punctuation

---

### ID 19 | Category: crossing_process | Field: answer
**Current:** `Limited basic facilitiesuse early.`
**Corrected:** `Limited basic facilities; use early.`
**Issues:** Missing space and punctuation

---

### ID 24 | Category: transport | Field: question
**Current:** `Bus or taxiwhats faster?`
**Corrected:** `Bus or taxi—what's faster?`
**Issues:** Missing space, missing apostrophe in "what's"

---

### ID 25 | Category: transport | Field: answer
**Current:** `Yesusually available around CIQ and malls.`
**Corrected:** `Yes; usually available around CIQ and malls.`
**Issues:** Missing space and punctuation

---

### ID 26 | Category: transport | Field: answer
**Current:** `Taxi/Grab ~20â30 min off-peak.`
**Corrected:** `Taxi/Grab ~20–30 min off-peak.`
**Issues:** Wrong dash in number range

---

### ID 31 | Category: costs | Field: answer
**Current:** `Usually low single digits (a few SGD or RM); fares can adjustconfirm at ticket counter or operator site.`
**Corrected:** `Usually low single digits (a few SGD or RM); fares can adjust—confirm at ticket counter or operator site.`
**Issues:** Missing space and em-dash

---

### ID 32 | Category: costs | Field: question
**Current:** `Taxi/Grab Singapore â JB clinic cost?`
**Corrected:** `Taxi/Grab Singapore → JB clinic cost?`
**Issues:** Wrong arrow symbol

---

### ID 32 | Category: costs | Field: answer
**Current:** `Commonly SGD 40â70 offpeak; can exceed this with surge or heavy jamsalways check the live estimate in the Grab app first.`
**Corrected:** `Commonly SGD 40–70 off-peak; can exceed this with surge or heavy jams—always check the live estimate in the Grab app first.`
**Issues:** Wrong dash, missing hyphen in "off-peak", missing space/em-dash

---

### ID 33 | Category: costs | Field: answer
**Current:** `Taxi often 10â20Ã bus price (time vs money trade); multiplier varies with surgecompare live Grab fare against posted bus fare.`
**Corrected:** `Taxi often 10–20× bus price (time vs money trade); multiplier varies with surge—compare live Grab fare against posted bus fare.`
**Issues:** Wrong dash, wrong multiplication symbol, missing space/em-dash

---

### ID 37 | Category: driving | Field: answer
**Current:** `Yesregister before entering Malaysia via JPJ VEP portal: https://vep.jpj.gov.my/ (process or rules can updateverify before travel).`
**Corrected:** `Yes; register before entering Malaysia via JPJ VEP portal: https://vep.jpj.gov.my/ (process or rules can update—verify before travel).`
**Issues:** Missing space/punctuation, missing space/em-dash

---

### ID 38 | Category: driving | Field: question
**Current:** `How do I top up Touch ân Go?`
**Corrected:** `How do I top up Touch 'n Go?`
**Issues:** Wrong apostrophe character

---

### ID 39 | Category: driving | Field: question
**Current:** `How much Touch ân Go balance to carry?`
**Corrected:** `How much Touch 'n Go balance to carry?`
**Issues:** Wrong apostrophe character

---

### ID 39 | Category: driving | Field: answer
**Current:** `RM30â50 covers tolls + buffer.`
**Corrected:** `RM30–50 covers tolls + buffer.`
**Issues:** Wrong dash in number range

---

### ID 40 | Category: driving | Field: answer
**Current:** `Street or plaza parkingcheck signage.`
**Corrected:** `Street or plaza parking—check signage.`
**Issues:** Missing space and em-dash

---

### ID 45 | Category: clinic_travel | Field: answer
**Current:** `About 10â25 minutes off-peak by car.`
**Corrected:** `About 10–25 minutes off-peak by car.`
**Issues:** Wrong dash in number range

---

### ID 46 | Category: clinic_travel | Field: answer
**Current:** `Yesavoid hard chewing after major work.`
**Corrected:** `Yes; avoid hard chewing after major work.`
**Issues:** Missing space and punctuation

---

### ID 47 | Category: clinic_travel | Field: answer
**Current:** `Yesplan extra return time if near peak.`
**Corrected:** `Yes; plan extra return time if near peak.`
**Issues:** Missing space and punctuation

---

### ID 48 | Category: clinic_travel | Field: answer
**Current:** `Many early evening; some extended hoursconfirm direct.`
**Corrected:** `Many early evening; some extended hours—confirm direct.`
**Issues:** Missing space and em-dash

---

### ID 50 | Category: clinic_travel | Field: answer
**Current:** `Related areaMount Austin includes several sub-zones.`
**Corrected:** `Related area—Mount Austin includes several sub-zones.`
**Issues:** Missing space and em-dash

---

### ID 54 | Category: health_safety | Field: answer
**Current:** `Yes for comfortnot antibiotics unless prescribed.`
**Corrected:** `Yes for comfort—not antibiotics unless prescribed.`
**Issues:** Missing space and em-dash

---

### ID 55 | Category: health_safety | Field: answer
**Current:** `Yesmost clinic districts have several.`
**Corrected:** `Yes; most clinic districts have several.`
**Issues:** Missing space and punctuation

---

### ID 59 | Category: immigration | Field: answer
**Current:** `Typical short-stay allowance (e.g. 30â90 days) varies by passport.`
**Corrected:** `Typical short-stay allowance (e.g. 30–90 days) varies by passport.`
**Issues:** Wrong dash in number range

---

### ID 61 | Category: pitfalls | Field: answer
**Current:** `Add 45â60 minutes if near peak times.`
**Corrected:** `Add 45–60 minutes if near peak times.`
**Issues:** Wrong dash in number range

---

### ID 66 | Category: return_followup | Field: answer
**Current:** `Peak evening (5â8) and Sunday late afternoon.`
**Corrected:** `Peak evening (5PM–8PM) and Sunday late afternoon.`
**Issues:** Wrong dash, missing PM indicators

---

### ID 67 | Category: return_followup | Field: answer
**Current:** `Yesschedule ride-hail or arrange pickup.`
**Corrected:** `Yes; schedule ride-hail or arrange pickup.`
**Issues:** Missing space and punctuation

---

### ID 68 | Category: return_followup | Field: answer
**Current:** `Usually fineconfirm clinic-specific instructions.`
**Corrected:** `Usually fine—confirm clinic-specific instructions.`
**Issues:** Missing space and em-dash

---

### ID 71 | Category: payments_currency | Field: answer
**Current:** `Enable travel notice & overseas usage to reduce declines; pay in MYR (avoid DCC). Typical FX fees ~1â3% but varycheck issuer. Keep backup card + some cash; ensure OTP/SMS works abroad.`
**Corrected:** `Enable travel notice & overseas usage to reduce declines; pay in MYR (avoid DCC). Typical FX fees ~1–3% but vary—check issuer. Keep backup card + some cash; ensure OTP/SMS works abroad.`
**Issues:** Wrong dash in range, missing space/em-dash

---

### ID 72 | Category: tech_connectivity | Field: answer
**Current:** `Options: (1) Local prepaid SIM/eSIM (Maxis/Celcom/Digi) ~RM10â30 starter packs,  (2) Regional eSIM apps,   (3) SG roaming daily pass (~SGD 5â10). Prices shiftcompare at purchase; enable roaming only when needed.`
**Corrected:** `Options: (1) Local prepaid SIM/eSIM (Maxis/Celcom/Digi) ~RM10–30 starter packs, (2) Regional eSIM apps, (3) SG roaming daily pass (~SGD 5–10). Prices shift—compare at purchase; enable roaming only when needed.`
**Issues:** Wrong dashes in ranges, missing space/em-dash

---

### ID 74 | Category: tech_connectivity | Field: answer
**Current:** `Helps if lateclinic can decide to hold slot.`
**Corrected:** `Helps if late—clinic can decide to hold slot.`
**Issues:** Missing space and em-dash

---

### ID 75 | Category: edge_emergency | Field: answer
**Current:** `Expect manual processing; patienceno shortcut.`
**Corrected:** `Expect manual processing; patience—no shortcut.`
**Issues:** Missing space and em-dash

---

### ID 77 | Category: appointments | Field: question
**Current:** `What if Im late for my appointment?`
**Corrected:** `What if I'm late for my appointment?`
**Issues:** Missing apostrophe in "I'm"

---

### ID 78 | Category: afterhours | Field: question
**Current:** `Overnight dental pain â what should I do?`
**Corrected:** `Overnight dental pain—what should I do?`
**Issues:** Wrong dash character

---

### ID 78 | Category: afterhours | Field: answer
**Current:** `We cant provide medical advice. If pain is severe  swelling or fever develops  or you have trouble breathing or swallowing  seek urgent care immediately. Otherwise  contact your clinic when it opens for professional assessment.`
**Corrected:** `We can't provide medical advice. If pain is severe, swelling or fever develops, or you have trouble breathing or swallowing, seek urgent care immediately. Otherwise, contact your clinic when it opens for professional assessment.`
**Issues:** Missing apostrophe in "can't", spaces instead of commas

---

### ID 80 | Category: payments_currency | Field: answer
**Current:** `Some larger or SGfocused clinics may offer PayNow/PayLah! or similar  but not guaranteedplan for MYR card payment or cash as fallback.`
**Corrected:** `Some larger or SG-focused clinics may offer PayNow/PayLah! or similar, but not guaranteed—plan for MYR card payment or cash as fallback.`
**Issues:** Missing hyphen in "SG-focused", spaces to comma, missing space/em-dash

---

### ID 81 | Category: post_treatment | Field: answer
**Current:** `We cannot give medical advice. Many people avoid alcohol for the rest of the day after invasive dental workfollow your dentists specific instructions.`
**Corrected:** `We cannot give medical advice. Many people avoid alcohol for the rest of the day after invasive dental work—follow your dentist's specific instructions.`
**Issues:** Missing space/em-dash, missing apostrophe in "dentist's"

---

### ID 82 | Category: post_treatment | Field: answer
**Current:** `We cannot give medical advice. Clinics often advise soft foods initially then gradual reintroductionconfirm the exact timeline with your dentist.`
**Corrected:** `We cannot give medical advice. Clinics often advise soft foods initially then gradual reintroduction—confirm the exact timeline with your dentist.`
**Issues:** Missing space and em-dash

---

### ID 83 | Category: safety | Field: answer
**Current:** `Popular zones (e.g. Mount Austin) are generally active and welllit; use standard travel sense: stay in public areas  pre-arrange transport  keep valuables minimal.`
**Corrected:** `Popular zones (e.g. Mount Austin) are generally active and well-lit; use standard travel sense: stay in public areas, pre-arrange transport, keep valuables minimal.`
**Issues:** Missing hyphen in "well-lit", spaces to commas

---

### ID 84 | Category: return_followup | Field: question
**Current:** `What if I need a follow-up but Im back in Singapore?`
**Corrected:** `What if I need a follow-up but I'm back in Singapore?`
**Issues:** Missing apostrophe in "I'm"

---

### ID 84 | Category: return_followup | Field: answer
**Current:** `Message the clinic (WhatsApp) with clear photos & description; they can advise remotely or schedule next inperson visitretain treatment notes & receipts.`
**Corrected:** `Message the clinic (WhatsApp) with clear photos & description; they can advise remotely or schedule next in-person visit—retain treatment notes & receipts.`
**Issues:** Missing hyphen in "in-person", missing space/em-dash

---

### ID 85 | Category: meta | Field: answer
**Current:** `General guidance accurate as of late 2025; dynamic items (costs  schedules  fees) can changeverify with official sources (KTM,  JPJ VEP,  Grab, FX sites)`
**Corrected:** `General guidance accurate as of late 2025; dynamic items (costs, schedules, fees) can change—verify with official sources (KTM, JPJ VEP, Grab, FX sites)`
**Issues:** Spaces to commas, missing space/em-dash

---

### ID 86 | Category: transport | Field: answer
**Current:** `Travel time varies by transport and traffic. Off-peak  expect 45â60 minutes from central Singapore to most JB clinics; peak hours can double this.`
**Corrected:** `Travel time varies by transport and traffic. Off-peak, expect 45–60 minutes from central Singapore to most JB clinics; peak hours can double this.`
**Issues:** Space to comma, wrong dash in range

---

### ID 90 | Category: clinic_travel | Field: answer
**Current:** `Most clinics are 10â25 minutes by taxi/Grab from CIQ. Some are walkable; check your clinics address and use navigation apps.`
**Corrected:** `Most clinics are 10–25 minutes by taxi/Grab from CIQ. Some are walkable; check your clinic's address and use navigation apps.`
**Issues:** Wrong dash, missing apostrophe in "clinic's"

---

### ID 91 | Category: clinic_travel | Field: answer
**Current:** `Taxi/Grab is easiest; expect 20â30 minutes off-peak. Buses are available but less direct.`
**Corrected:** `Taxi/Grab is easiest; expect 20–30 minutes off-peak. Buses are available but less direct.`
**Issues:** Wrong dash in range

---

### ID 92 | Category: clinic_travel | Field: answer
**Current:** `Taxi/Grab is fastest; bus options exist but may require transfers. Plan for 20â30 minutes off-peak.`
**Corrected:** `Taxi/Grab is fastest; bus options exist but may require transfers. Plan for 20–30 minutes off-peak.`
**Issues:** Wrong dash in range

---

### ID 93 | Category: clinic_travel | Field: answer
**Current:** `Taxi/Grab is recommended; bus routes are available but less direct. Travel time 20â40 minutes off-peak.`
**Corrected:** `Taxi/Grab is recommended; bus routes are available but less direct. Travel time 20–40 minutes off-peak.`
**Issues:** Wrong dash in range

---

### ID 96 | Category: timing | Field: answer
**Current:** `Weekdays (TuesdayThursday) are usually less crowded than weekends. Avoid Friday evenings and Sunday late afternoons for return.`
**Corrected:** `Weekdays (Tuesday–Thursday) are usually less crowded than weekends. Avoid Friday evenings and Sunday late afternoons for return.`
**Issues:** Missing dash between days

---

### ID 97 | Category: clinic_travel | Field: answer
**Current:** `Most townships and clinics in JB are accessible by taxi/Grab from CIQ. Travel times range from 10 to 45 minutes depending on distance and traffic. For rare or less-known areas  check your clinics address and use navigation apps for the best route.`
**Corrected:** `Most townships and clinics in JB are accessible by taxi/Grab from CIQ. Travel times range from 10 to 45 minutes depending on distance and traffic. For rare or less-known areas, check your clinic's address and use navigation apps for the best route.`
**Issues:** Space to comma, missing apostrophe in "clinic's"

---

## RECOMMENDED ACTION PLAN

1. **Create SQL UPDATE statements** for each affected row
2. **Test on a single FAQ** first to verify the correction works
3. **Batch update** all 54 FAQs
4. **Re-index embeddings** if the text changes affect semantic search
5. **Verify** no new encoding issues were introduced

## ENCODING ROOT CAUSE

These are Windows-1252 (CP-1252) control characters that were incorrectly stored as UTF-8. The original text likely had:
- Proper em-dashes (—)
- Proper apostrophes (')
- Proper quotes (" ")
- Proper en-dashes (–)

But they were corrupted during data entry or import, likely from copying from a Windows application or Word document that uses CP-1252 encoding.

---

**Report Generated:** December 1, 2025
**Analysis Tool:** Python with Supabase Client
**Database:** uzppuebjzqxeavgmwtvr.supabase.co
