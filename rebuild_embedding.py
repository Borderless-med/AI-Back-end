import os
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client
import time

# --- Configuration ---
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
gemini_api_key = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=gemini_api_key)

# The new standard model (768 dimensions)
embedding_model = 'models/text-embedding-004'

# --- 1. Define Sentiment Mapping ---
SENTIMENT_MAPPING = {
    'sentiment_dentist_skill': 'highly skilled dentists',
    'sentiment_pain_management': 'gentle and painless treatment',
    'sentiment_cost_value': 'good value for money',
    'sentiment_staff_service': 'friendly and helpful staff',
    'sentiment_ambiance_cleanliness': 'a clean and modern environment',
    'sentiment_convenience': 'convenient and on-time appointments'
}

# --- 2. Define Service Mapping ---
# Ensure these column names exist in BOTH 'clinics_data' and 'sg_clinics'
SERVICE_MAPPING = {
    'braces': 'Orthodontics and Braces',
    'dental_implant': 'Dental Implants',
    'root_canal': 'Root Canal Treatment',
    'whitening': 'Teeth Whitening',
    'wisdom_tooth': 'Wisdom Tooth Surgery',
    'crown': 'Dental Crowns and Bridges',
    'veneers': 'Veneers',
    'scaling': 'Scaling and Polishing',
    'filling': 'Fillings',
    'kids_dentistry': 'Pediatric Dentistry',
    'xray': 'Dental X-Ray'
}

def generate_embedding(text):
    try:
        result = genai.embed_content(
            model=embedding_model,
            content=text,
            task_type="retrieval_document"
        )
        return result['embedding']
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def process_table(table_name):
    print(f"\n🚀 Processing Table: {table_name}...")
    
    # Build column list dynamically to avoid fetching the old 'embedding'
    base_cols = ["id", "name", "address"]
    sentiment_cols = list(SENTIMENT_MAPPING.keys())
    service_cols = list(SERVICE_MAPPING.keys())
    
    all_cols = base_cols + sentiment_cols + service_cols
    query_string = ",".join(all_cols)
    
    try:
        response = supabase.table(table_name).select(query_string).execute()
        clinics = response.data
        print(f"✅ Found {len(clinics)} records in {table_name}.")
    except Exception as e:
        print(f"CRITICAL ERROR fetching {table_name}: {e}")
        print("Possible cause: A column defined in SERVICE_MAPPING is missing from this table.")
        return

    for clinic in clinics:
        clinic_id = clinic['id']
        name = clinic.get('name', '') or ''
        address = clinic.get('address', '') or ''
        
        # A. Build Sentiment Text
        sentiment_text = []
        for col, desc in SENTIMENT_MAPPING.items():
            val = clinic.get(col)
            try:
                if val and float(val) > 8.0:
                    sentiment_text.append(desc)
            except (ValueError, TypeError):
                continue

        # B. Build Service Text
        service_text = []
        for col, desc in SERVICE_MAPPING.items():
            if clinic.get(col) is True:
                service_text.append(desc)

        # C. Combine
        full_text = f"{name}. {address}."
        if service_text:
            full_text += f" Services: {', '.join(service_text)}."
        if sentiment_text:
            full_text += f" Highlights: {', '.join(sentiment_text)}."
        
        # Log (Concise)
        print(f"[{table_name}] ID {clinic_id}: {name[:15]}... | Svc: {len(service_text)}")

        # D. Generate & Save
        vector = generate_embedding(full_text)

        if vector:
            try:
                supabase.table(table_name).update({
                    "embedding": vector 
                }).eq("id", clinic_id).execute()
                time.sleep(0.1) # Fast but polite
            except Exception as e:
                print(f"Error saving ID {clinic_id}: {e}")
        else:
            print(f"Skipping {clinic_id}: Embedding failed.")

if __name__ == "__main__":
    # Process JB then SG
    process_table("clinics_data") 
    process_table("sg_clinics")
    print("\n🎉 ALL TABLES RE-INDEXED SUCCESSFULLY.")