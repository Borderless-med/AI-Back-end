"""
Script to show detailed garbled text with actual characters visible.
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

def find_problematic_chars(text):
    """Find and display problematic characters with their hex codes."""
    if not text:
        return []
    
    issues = []
    
    # Find em-dash or en-dash characters that might be garbled
    for i, char in enumerate(text):
        ord_val = ord(char)
        
        # Control characters (0x00-0x1F, 0x7F-0x9F)
        if (0x00 <= ord_val <= 0x1F) or (0x7F <= ord_val <= 0x9F):
            # Get context around the character
            start = max(0, i - 20)
            end = min(len(text), i + 20)
            context_before = text[start:i]
            context_after = text[i+1:end]
            
            issues.append({
                'char': repr(char),
                'hex': f'0x{ord_val:02X}',
                'position': i,
                'context_before': context_before,
                'context_after': context_after,
                'full_context': f'{context_before}[{repr(char)}]{context_after}'
            })
    
    return issues

def main():
    print("=" * 100)
    print("DETAILED GARBLED TEXT ANALYSIS")
    print("=" * 100)
    print()
    
    try:
        # Query all FAQs
        response = supabase.table("faqs_semantic").select("id, category, question, answer").order("id").execute()
        
        faqs = response.data
        print(f"Total FAQs retrieved: {len(faqs)}\n")
        
        # Track all corrections needed
        corrections_needed = []
        
        # Analyze each FAQ
        for faq in faqs:
            faq_id = faq['id']
            category = faq['category']
            question = faq['question']
            answer = faq['answer']
            
            # Check question
            question_issues = find_problematic_chars(question)
            if question_issues:
                for issue in question_issues:
                    corrections_needed.append({
                        'id': faq_id,
                        'category': category,
                        'field': 'question',
                        'char': issue['char'],
                        'hex': issue['hex'],
                        'context': issue['full_context'],
                        'full_text': question
                    })
            
            # Check answer
            answer_issues = find_problematic_chars(answer)
            if answer_issues:
                for issue in answer_issues:
                    corrections_needed.append({
                        'id': faq_id,
                        'category': category,
                        'field': 'answer',
                        'char': issue['char'],
                        'hex': issue['hex'],
                        'context': issue['full_context'],
                        'full_text': answer
                    })
        
        # Print detailed results
        if corrections_needed:
            print(f"\nFOUND {len(corrections_needed)} GARBLED CHARACTER INSTANCES\n")
            print("=" * 100)
            
            # Group by FAQ ID
            current_id = None
            for item in corrections_needed:
                if item['id'] != current_id:
                    current_id = item['id']
                    print(f"\n{'=' * 100}")
                    print(f"FAQ ID: {item['id']} | Category: {item['category']}")
                    print('=' * 100)
                
                print(f"\nField: {item['field']}")
                print(f"Garbled Character: {item['char']} (hex: {item['hex']})")
                print(f"Context: {item['context']}")
                print(f"\nFull {item['field']} text:")
                print(f"{item['full_text'][:300]}...")
                print("-" * 100)
        
        else:
            print("✓ No garbled characters found!")
        
        print(f"\n\n{'=' * 100}")
        print("ANALYSIS COMPLETE")
        print("=" * 100)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
