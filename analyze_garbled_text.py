"""
Script to identify ALL garbled text patterns in the faqs_semantic table.
Analyzes question and answer columns for encoding issues.
"""

import os
import re
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not found in .env file")

supabase: Client = create_client(supabase_url, supabase_key)

def analyze_text_for_garbling(text):
    """
    Analyze text for various types of garbled characters.
    Returns list of issues found.
    """
    if not text:
        return []
    
    issues = []
    
    # Pattern 1: Unicode replacement character (�)
    if '�' in text:
        # Find all occurrences with context
        for match in re.finditer(r'.{0,20}�+.{0,20}', text):
            issues.append({
                'pattern': 'Unicode replacement character (�)',
                'garbled': match.group(0).strip(),
                'context': match.group(0).strip()
            })
    
    # Pattern 2: Double pipe characters (||)
    if '||' in text:
        for match in re.finditer(r'.{0,20}\|\|.{0,20}', text):
            issues.append({
                'pattern': 'Double pipe (||)',
                'garbled': match.group(0).strip(),
                'context': match.group(0).strip()
            })
    
    # Pattern 3: Unusual character sequences that might indicate encoding issues
    # Check for sequences like ã, â, ¢, º, etc. commonly from encoding problems
    encoding_chars = re.findall(r'[^\x00-\x7F\u0080-\u00FF\u2000-\u206F\u2070-\u209F\u20A0-\u20CF\u2100-\u214F\u2150-\u218F\u2190-\u21FF\u2200-\u22FF\u2300-\u23FF\u2460-\u24FF\u2500-\u257F\u2580-\u259F\u25A0-\u25FF\u2600-\u26FF\u2700-\u27BF\u2800-\u28FF\u2900-\u297F\u2980-\u29FF\u2A00-\u2AFF\u2B00-\u2BFF\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u3100-\u312F\u3130-\u318F\u3190-\u319F\u31A0-\u31BF\u31F0-\u31FF\u3200-\u32FF\u3300-\u33FF\u3400-\u4DBF\u4DC0-\u4DFF\u4E00-\u9FFF\uA000-\uA48F\uA490-\uA4CF\uAC00-\uD7AF\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFFEF]', text)
    if encoding_chars:
        issues.append({
            'pattern': 'Unusual unicode characters',
            'garbled': ', '.join(set(encoding_chars[:10])),  # Show first 10 unique chars
            'context': 'Multiple unusual characters found'
        })
    
    # Pattern 4: Check for common encoding error patterns
    encoding_patterns = [
        (r'â€™', "Should be apostrophe (')"),
        (r'â€œ|â€', 'Should be double quotes ("")'),
        (r'â€"', 'Should be em-dash (—)'),
        (r'Â', 'Extra Â character'),
        (r'ã', 'Encoding issue with ã'),
        (r'º', 'Encoding issue with º'),
    ]
    
    for pattern, description in encoding_patterns:
        if re.search(pattern, text):
            for match in re.finditer(f'.{{0,20}}{pattern}.{{0,20}}', text):
                issues.append({
                    'pattern': description,
                    'garbled': match.group(0).strip(),
                    'context': match.group(0).strip()
                })
    
    # Pattern 5: Check for sequences of non-printable or control characters
    control_chars = re.findall(r'[\x00-\x1F\x7F-\x9F]', text)
    if control_chars:
        issues.append({
            'pattern': 'Control/non-printable characters',
            'garbled': f'{len(control_chars)} control characters found',
            'context': 'Non-printable characters in text'
        })
    
    return issues

def main():
    print("=" * 80)
    print("GARBLED TEXT ANALYSIS FOR faqs_semantic TABLE")
    print("=" * 80)
    print()
    
    try:
        # Query all FAQs
        response = supabase.table("faqs_semantic").select("id, category, question, answer").order("id").execute()
        
        faqs = response.data
        print(f"Total FAQs retrieved: {len(faqs)}\n")
        
        # Store all issues
        all_issues = []
        
        # Analyze each FAQ
        for faq in faqs:
            faq_id = faq['id']
            category = faq['category']
            question = faq['question']
            answer = faq['answer']
            
            # Check question
            question_issues = analyze_text_for_garbling(question)
            for issue in question_issues:
                all_issues.append({
                    'id': faq_id,
                    'category': category,
                    'field': 'question',
                    'pattern': issue['pattern'],
                    'garbled': issue['garbled'],
                    'current_text': question,
                    'context': issue['context']
                })
            
            # Check answer
            answer_issues = analyze_text_for_garbling(answer)
            for issue in answer_issues:
                all_issues.append({
                    'id': faq_id,
                    'category': category,
                    'field': 'answer',
                    'pattern': issue['pattern'],
                    'garbled': issue['garbled'],
                    'current_text': answer,
                    'context': issue['context']
                })
        
        # Print results
        if all_issues:
            print(f"FOUND {len(all_issues)} GARBLING ISSUES:\n")
            print("=" * 80)
            
            for idx, issue in enumerate(all_issues, 1):
                print(f"\n{idx}. ID: {issue['id']} | Category: {issue['category']} | Field: {issue['field']}")
                print(f"   Pattern: {issue['pattern']}")
                print(f"   Garbled text: {issue['garbled']}")
                print(f"   Context: {issue['context'][:100]}...")
                print(f"   Full {issue['field']}:")
                print(f"   {issue['current_text'][:200]}...")
                print("-" * 80)
            
            # Summary by pattern type
            print("\n" + "=" * 80)
            print("SUMMARY BY PATTERN TYPE:")
            print("=" * 80)
            pattern_counts = {}
            for issue in all_issues:
                pattern = issue['pattern']
                if pattern not in pattern_counts:
                    pattern_counts[pattern] = 0
                pattern_counts[pattern] += 1
            
            for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"{pattern}: {count} occurrences")
            
            # Detailed report - show specific examples
            print("\n" + "=" * 80)
            print("DETAILED CORRECTIONS NEEDED:")
            print("=" * 80)
            
            # Group by ID for easier correction
            issues_by_id = {}
            for issue in all_issues:
                faq_id = issue['id']
                if faq_id not in issues_by_id:
                    issues_by_id[faq_id] = []
                issues_by_id[faq_id].append(issue)
            
            for faq_id in sorted(issues_by_id.keys()):
                issues = issues_by_id[faq_id]
                print(f"\nID {faq_id}: {len(issues)} issue(s)")
                for issue in issues:
                    print(f"  - {issue['field']}: {issue['pattern']}")
                    print(f"    Garbled: {issue['garbled']}")
        
        else:
            print("✓ No garbled text patterns found in the database!")
        
        print("\n" + "=" * 80)
        print(f"Analysis complete. Checked {len(faqs)} FAQs.")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
