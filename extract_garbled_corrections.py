"""
Script to extract garbled text and create correction table.
Exports to CSV for easy viewing and correction.
"""

import os
import csv
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not found in .env file")

supabase: Client = create_client(supabase_url, supabase_key)

def find_garbled_patterns(text):
    """Find garbled patterns and suggest corrections."""
    if not text:
        return []
    
    patterns = []
    
    # Common garbled patterns based on Windows-1252 to UTF-8 issues
    replacements = {
        '\x80': '—',  # Em dash
        '\x93': '"',  # Left double quote
        '\x94': '"',  # Right double quote
        '\x91': ''',  # Left single quote
        '\x92': ''',  # Right single quote
        '\x96': '–',  # En dash
        '\x97': '—',  # Em dash
        '\x85': '…',  # Ellipsis
    }
    
    for i, char in enumerate(text):
        if char in replacements:
            start = max(0, i - 30)
            end = min(len(text), i + 30)
            context = text[start:end]
            
            patterns.append({
                'garbled_char': f"0x{ord(char):02X}",
                'should_be': replacements[char],
                'position': i,
                'context': context.replace(char, f"[{replacements[char]}]")
            })
    
    return patterns

def correct_text(text):
    """Apply all corrections to text."""
    if not text:
        return text
    
    replacements = {
        '\x80': '—',
        '\x93': '"',
        '\x94': '"',
        '\x91': ''',
        '\x92': ''',
        '\x96': '–',
        '\x97': '—',
        '\x85': '…',
    }
    
    corrected = text
    for old, new in replacements.items():
        corrected = corrected.replace(old, new)
    
    return corrected

def main():
    print("Fetching FAQs from database...")
    
    try:
        # Query all FAQs
        response = supabase.table("faqs_semantic").select("id, category, question, answer").order("id").execute()
        
        faqs = response.data
        print(f"Total FAQs retrieved: {len(faqs)}")
        
        # Collect all corrections
        corrections = []
        
        for faq in faqs:
            faq_id = faq['id']
            category = faq['category']
            question = faq['question']
            answer = faq['answer']
            
            # Check question
            question_patterns = find_garbled_patterns(question)
            if question_patterns:
                corrected_question = correct_text(question)
                corrections.append({
                    'ID': faq_id,
                    'Category': category,
                    'Field': 'question',
                    'Garbled_Count': len(question_patterns),
                    'Current_Text': question,
                    'Corrected_Text': corrected_question,
                    'Pattern_Type': 'Windows-1252 encoding issue'
                })
            
            # Check answer
            answer_patterns = find_garbled_patterns(answer)
            if answer_patterns:
                corrected_answer = correct_text(answer)
                corrections.append({
                    'ID': faq_id,
                    'Category': category,
                    'Field': 'answer',
                    'Garbled_Count': len(answer_patterns),
                    'Current_Text': answer,
                    'Corrected_Text': corrected_answer,
                    'Pattern_Type': 'Windows-1252 encoding issue'
                })
        
        # Save to CSV
        if corrections:
            csv_file = 'garbled_text_corrections.csv'
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                fieldnames = ['ID', 'Category', 'Field', 'Garbled_Count', 'Pattern_Type', 'Current_Text', 'Corrected_Text']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(corrections)
            
            print(f"\n✓ Found {len(corrections)} FAQs with garbled text")
            print(f"✓ Corrections saved to: {csv_file}")
            
            # Print summary
            print("\n" + "=" * 80)
            print("SUMMARY OF CORRECTIONS NEEDED:")
            print("=" * 80)
            
            for correction in corrections:
                print(f"\nID {correction['ID']} ({correction['Category']}) - {correction['Field']}")
                print(f"  {correction['Garbled_Count']} garbled character(s)")
                print(f"  Current: {correction['Current_Text'][:80]}...")
                print(f"  Corrected: {correction['Corrected_Text'][:80]}...")
            
            print("\n" + "=" * 80)
            print(f"Total: {len(corrections)} corrections needed")
            print("=" * 80)
            
        else:
            print("\n✓ No garbled text found!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
