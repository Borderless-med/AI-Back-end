"""
Complete analysis showing EVERY garbled character with hex codes and proper corrections.
This creates a detailed table for manual review.
"""

import os
import csv
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Missing credentials")

supabase: Client = create_client(supabase_url, supabase_key)

def get_char_info(char):
    """Get detailed info about a character."""
    code = ord(char)
    if code <= 0x1F or (0x7F <= code <= 0x9F):
        return f"0x{code:02X} (control char)"
    elif code > 127:
        return f"0x{code:02X} ('{char}')"
    else:
        return f"'{char}'"

def suggest_correction(text):
    """
    Suggest proper correction for garbled text.
    Based on common Windows-1252 encoding issues.
    """
    if not text:
        return text
    
    # Windows-1252 to proper UTF-8 mapping
    corrections = {
        '\x80': '—',   # Euro sign displayed as em-dash context
        '\x82': ',',   # Single low-9 quotation
        '\x83': 'f',   # Latin small f with hook
        '\x84': '„',   # Double low-9 quotation
        '\x85': '…',   # Ellipsis
        '\x86': '†',   # Dagger
        '\x87': '‡',   # Double dagger
        '\x88': 'ˆ',   # Circumflex
        '\x89': '‰',   # Per mille
        '\x8A': 'Š',   # S with caron
        '\x8B': '‹',   # Single left angle quote
        '\x8C': 'Œ',   # OE ligature
        '\x8E': 'Ž',   # Z with caron
        '\x91': ''',   # Left single quote
        '\x92': ''',   # Right single quote
        '\x93': '"',   # Left double quote
        '\x94': '"',   # Right double quote
        '\x95': '•',   # Bullet
        '\x96': '–',   # En dash
        '\x97': '—',   # Em dash
        '\x98': '˜',   # Small tilde
        '\x99': '™',   # Trademark
        '\x9A': 'š',   # s with caron
        '\x9B': '›',   # Single right angle quote
        '\x9C': 'œ',   # oe ligature
        '\x9E': 'ž',   # z with caron
        '\x9F': 'Ÿ',   # Y with diaeresis
    }
    
    corrected = text
    for old, new in corrections.items():
        corrected = corrected.replace(old, new)
    
    # Additional context-based fixes
    # "7—9" should likely be "7AM–9:30AM" or similar based on context
    # "Yes—" followed by text should be "Yes; " or "Yes—"
    
    return corrected

def main():
    print("Querying database...")
    
    response = supabase.table("faqs_semantic").select("id, category, question, answer").order("id").execute()
    faqs = response.data
    
    print(f"Analyzing {len(faqs)} FAQs for garbled text...\n")
    
    # Collect all instances with garbled characters
    garbled_instances = []
    
    for faq in faqs:
        faq_id = faq['id']
        category = faq['category']
        question = faq['question'] or ''
        answer = faq['answer'] or ''
        
        # Check each character in question
        for i, char in enumerate(question):
            code = ord(char)
            if code <= 0x1F or (0x7F <= code <= 0x9F):
                # Get context
                start = max(0, i - 30)
                end = min(len(question), i + 30)
                context = question[start:end]
                
                garbled_instances.append({
                    'ID': faq_id,
                    'Category': category,
                    'Field': 'question',
                    'Char_Hex': f"0x{code:02X}",
                    'Position': i,
                    'Context': context.replace(char, f'[HEX:{code:02X}]'),
                    'Full_Original': question,
                    'Suggested_Fix': suggest_correction(question)
                })
        
        # Check each character in answer
        for i, char in enumerate(answer):
            code = ord(char)
            if code <= 0x1F or (0x7F <= code <= 0x9F):
                start = max(0, i - 30)
                end = min(len(answer), i + 30)
                context = answer[start:end]
                
                garbled_instances.append({
                    'ID': faq_id,
                    'Category': category,
                    'Field': 'answer',
                    'Char_Hex': f"0x{code:02X}",
                    'Position': i,
                    'Context': context.replace(char, f'[HEX:{code:02X}]'),
                    'Full_Original': answer,
                    'Suggested_Fix': suggest_correction(answer)
                })
    
    if garbled_instances:
        print(f"Found {len(garbled_instances)} garbled character instances!\n")
        
        # Group by FAQ ID for summary
        by_faq = {}
        for inst in garbled_instances:
            key = (inst['ID'], inst['Field'])
            if key not in by_faq:
                by_faq[key] = []
            by_faq[key].append(inst)
        
        # Print summary table
        print("=" * 120)
        print(f"{'ID':<4} | {'Category':<20} | {'Field':<10} | {'Hex Codes Found':<30} | {'Count':<5}")
        print("-" * 120)
        
        for (faq_id, field), instances in sorted(by_faq.items()):
            category = instances[0]['Category']
            hex_codes = ', '.join(set([inst['Char_Hex'] for inst in instances]))
            count = len(instances)
            print(f"{faq_id:<4} | {category:<20} | {field:<10} | {hex_codes:<30} | {count:<5}")
        
        # Save detailed CSV
        csv_file = 'complete_garbled_analysis.csv'
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            fieldnames = ['ID', 'Category', 'Field', 'Char_Hex', 'Context', 'Full_Original', 'Suggested_Fix']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            # Write unique entries (one per FAQ+Field combination)
            written = set()
            for inst in garbled_instances:
                key = (inst['ID'], inst['Field'])
                if key not in written:
                    written.add(key)
                    writer.writerow({
                        'ID': inst['ID'],
                        'Category': inst['Category'],
                        'Field': inst['Field'],
                        'Char_Hex': ', '.join(set([i['Char_Hex'] for i in by_faq[key]])),
                        'Context': inst['Context'][:100],
                        'Full_Original': inst['Full_Original'],
                        'Suggested_Fix': inst['Suggested_Fix']
                    })
        
        print(f"\n✓ Complete analysis saved to: {csv_file}")
        
        # Characterize the hex codes found
        print("\n" + "=" * 120)
        print("HEX CODE FREQUENCY:")
        print("=" * 120)
        
        hex_freq = {}
        for inst in garbled_instances:
            hex_code = inst['Char_Hex']
            if hex_code not in hex_freq:
                hex_freq[hex_code] = 0
            hex_freq[hex_code] += 1
        
        for hex_code, count in sorted(hex_freq.items(), key=lambda x: x[1], reverse=True):
            decimal = int(hex_code, 16)
            suggested = suggest_correction(chr(decimal))
            if suggested != chr(decimal):
                suggested_char = suggested
            else:
                suggested_char = "?"
            print(f"{hex_code}: {count} occurrences → Should be: '{suggested_char}'")
        
        print("\n" + "=" * 120)
        print(f"TOTAL: {len(by_faq)} FAQs need correction")
        print("=" * 120)
    
    else:
        print("✓ No garbled characters found!")

if __name__ == "__main__":
    main()
