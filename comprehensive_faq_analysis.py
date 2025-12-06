"""
Final comprehensive analysis with proper corrections.
This script identifies garbled patterns and provides human-readable corrections.
"""

import os
import re
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Missing credentials")

supabase: Client = create_client(supabase_url, supabase_key)

def analyze_and_correct(text):
    """
    Analyze text and return proper corrections.
    Based on the patterns, these are Windows-1252 characters that should be:
    - \x80 or â (when followed by certain chars) = em-dash (—) or en-dash (–) 
    - \x93\x94 or similar = quotes
    - 'ân' should probably be 'n' (apostrophe + n)
    """
    if not text:
        return text, []
    
    issues = []
    corrected = text
    
    # Pattern 1: "Yesâ" patterns (missing space and dash)
    # These appear to be: Yes[em-dash][space] that got corrupted
    if re.search(r'\w+(â|—)\w+', text):
        # Find words smashed together with weird chars
        pattern = re.compile(r'(\w+)(â|—|â€")(\w+)')
        for match in pattern.finditer(text):
            before, sep, after = match.groups()
            # Determine if this should be: space, em-dash+space, or something else
            # Most common pattern: "Yesconfirm" should be "Yes—confirm" or "Yes; confirm"
            
            # Check if it's a common pattern
            if before in ['Yes', 'No', 'Often']:
                fixed = f'{before}—{after}'
                issues.append({
                    'original': match.group(0),
                    'corrected': fixed,
                    'type': 'Missing em-dash and space'
                })
                corrected = corrected.replace(match.group(0), fixed)
            else:
                fixed = f'{before}; {after}'
                issues.append({
                    'original': match.group(0),
                    'corrected': fixed,
                    'type': 'Missing semicolon and space'
                })
                corrected = corrected.replace(match.group(0), fixed)
    
    # Pattern 2: Time ranges like "7â9:30" should be "7AM–9:30AM" or "7–9:30"
    time_pattern = re.compile(r'(\d+)(â|—)(\d+:?\d*)')
    for match in time_pattern.finditer(text):
        start, sep, end = match.groups()
        fixed = f'{start}–{end}'  # Use en-dash for ranges
        issues.append({
            'original': match.group(0),
            'corrected': fixed,
            'type': 'Time range with wrong dash'
        })
        corrected = corrected.replace(match.group(0), fixed)
    
    # Pattern 3: "Touch ân Go" should be "Touch 'n Go"
    if 'ân' in text:
        corrected = corrected.replace('ân', "'n")
        issues.append({
            'original': 'ân',
            'corrected': "'n",
            'type': 'Apostrophe + n'
        })
    
    # Pattern 4: "Im" should be "I'm"
    if 'Im ' in text or text.endswith('Im'):
        corrected = corrected.replace('Im ', "I'm ").replace('Im?', "I'm?")
        issues.append({
            'original': 'Im',
            'corrected': "I'm",
            'type': 'Missing apostrophe in contraction'
        })
    
    # Pattern 5: "whats" should be "what's"
    if 'whats' in text.lower():
        corrected = re.sub(r'\bwhats\b', "what's", corrected, flags=re.IGNORECASE)
        issues.append({
            'original': 'whats',
            'corrected': "what's",
            'type': 'Missing apostrophe in contraction'
        })
    
    # Pattern 6: "cant" should be "can't"
    if 'cant ' in text.lower() or 'cant.' in text.lower():
        corrected = re.sub(r'\bcant\b', "can't", corrected, flags=re.IGNORECASE)
        issues.append({
            'original': 'cant',
            'corrected': "can't",
            'type': 'Missing apostrophe in contraction'
        })
    
    # Pattern 7: "dentists" in context of "your dentists instructions" should be "dentist's"
    if 'dentists specific' in text or 'dentists instructions' in text:
        corrected = corrected.replace('dentists specific', "dentist's specific")
        corrected = corrected.replace('dentists instructions', "dentist's instructions")
        issues.append({
            'original': 'dentists',
            'corrected': "dentist's",
            'type': 'Missing possessive apostrophe'
        })
    
    # Pattern 8: "clinics address" should be "clinic's address"
    if 'clinics address' in text:
        corrected = corrected.replace('clinics address', "clinic's address")
        issues.append({
            'original': 'clinics address',
            'corrected': "clinic's address",
            'type': 'Missing possessive apostrophe'
        })
    
    # Pattern 9: "Ã" should be "×" (multiplication sign)
    if 'Ã' in text:
        corrected = corrected.replace('Ã', '×')
        issues.append({
            'original': 'Ã',
            'corrected': '×',
            'type': 'Wrong multiplication symbol'
        })
    
    # Pattern 10: Words smashed together without the dash
    smashed_patterns = [
        (r'offpeak', 'off-peak'),
        (r'inperson', 'in-person'),
        (r'welllit', 'well-lit'),
        (r'SGfocused', 'SG-focused'),
    ]
    
    for pattern, replacement in smashed_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
            issues.append({
                'original': pattern,
                'corrected': replacement,
                'type': 'Missing hyphen in compound word'
            })
    
    return corrected, issues

def main():
    print("=" * 100)
    print("COMPREHENSIVE GARBLED TEXT ANALYSIS & CORRECTIONS")
    print("=" * 100)
    print()
    
    try:
        response = supabase.table("faqs_semantic").select("id, category, question, answer").order("id").execute()
        faqs = response.data
        print(f"Analyzing {len(faqs)} FAQs...\n")
        
        all_corrections = []
        
        for faq in faqs:
            faq_id = faq['id']
            category = faq['category']
            question = faq['question']
            answer = faq['answer']
            
            # Analyze question
            corrected_q, q_issues = analyze_and_correct(question)
            if q_issues and corrected_q != question:
                all_corrections.append({
                    'id': faq_id,
                    'category': category,
                    'field': 'question',
                    'original': question,
                    'corrected': corrected_q,
                    'issues': q_issues
                })
            
            # Analyze answer
            corrected_a, a_issues = analyze_and_correct(answer)
            if a_issues and corrected_a != answer:
                all_corrections.append({
                    'id': faq_id,
                    'category': category,
                    'field': 'answer',
                    'original': answer,
                    'corrected': corrected_a,
                    'issues': a_issues
                })
        
        # Print results in table format
        if all_corrections:
            print(f"FOUND {len(all_corrections)} ITEMS NEEDING CORRECTION\n")
            print("=" * 100)
            
            print(f"{'ID':<4} | {'Category':<20} | {'Field':<10} | {'Issues':<60}")
            print("-" * 100)
            
            for item in all_corrections:
                issues_summary = ', '.join([f"{i['original']}→{i['corrected']}" for i in item['issues'][:2]])
                if len(item['issues']) > 2:
                    issues_summary += f" +{len(item['issues'])-2} more"
                print(f"{item['id']:<4} | {item['category']:<20} | {item['field']:<10} | {issues_summary[:58]}")
            
            # Detailed printout
            print("\n" + "=" * 100)
            print("DETAILED CORRECTIONS:")
            print("=" * 100)
            
            for idx, item in enumerate(all_corrections, 1):
                print(f"\n{idx}. FAQ ID: {item['id']} | Category: {item['category']} | Field: {item['field']}")
                print(f"   Issues found: {len(item['issues'])}")
                for issue in item['issues']:
                    print(f"   - {issue['type']}: '{issue['original']}' → '{issue['corrected']}'")
                print(f"\n   ORIGINAL:")
                print(f"   {item['original'][:150]}...")
                print(f"\n   CORRECTED:")
                print(f"   {item['corrected'][:150]}...")
                print("-" * 100)
            
            # Save to file
            with open('detailed_corrections_needed.txt', 'w', encoding='utf-8') as f:
                f.write("COMPREHENSIVE CORRECTIONS FOR faqs_semantic TABLE\n")
                f.write("=" * 100 + "\n\n")
                
                for item in all_corrections:
                    f.write(f"FAQ ID: {item['id']}\n")
                    f.write(f"Category: {item['category']}\n")
                    f.write(f"Field: {item['field']}\n")
                    f.write(f"Issues: {len(item['issues'])}\n")
                    for issue in item['issues']:
                        f.write(f"  - {issue['type']}: '{issue['original']}' → '{issue['corrected']}'\n")
                    f.write(f"\nORIGINAL:\n{item['original']}\n")
                    f.write(f"\nCORRECTED:\n{item['corrected']}\n")
                    f.write("\n" + "-" * 100 + "\n\n")
            
            print(f"\n✓ Detailed report saved to: detailed_corrections_needed.txt")
            print(f"\n{'=' * 100}")
            print(f"SUMMARY: {len(all_corrections)} corrections needed across {len(faqs)} FAQs")
            print("=" * 100)
        
        else:
            print("✓ No corrections needed!")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
