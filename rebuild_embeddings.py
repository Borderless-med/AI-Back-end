import os
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client
import time

# --- Configuration ---
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
embedding_model = 'models/embedding-001'

# --- Define the service and sentiment columns ---
SERVICE_COLUMNS = [
    'tooth_filling', 'root_canal', 'dental_crown', 'dental_implant', 'wisdom_tooth', 'gum_treatment',
    'dental_bonding', 'inlays_onlays', 'teeth_whitening', 'composite_veneers', 'porcelain_veneers',
    'enamel_shaping', 'braces', 'gingivectomy', 'bone_grafting', 'sinus_lift', 'frenectomy',
    'tmj_treatment', 'sleep_apnea_appliances', 'crown_lengthening', 'oral_cancer_screening', 'alveoplasty'
]
SENTIMENT_MAPPING = {
    'sentiment_dentist_skill': 'highly skilled dentists',
    'sentiment_pain_management': 'gentle and painless treatment',
    'sentiment_cost_value': 'good value for money',
    'sentiment_staff_service': 'friendly and helpful staff',
    'sentiment_ambiance_cleanliness': 'a clean and modern environment',
    'sentiment_convenience': 'convenient and on-time appointments'
}

def rebuild_all_embeddings():
    print("Starting the new, standardized embedding rebuild process...")
    
    # 1. Fetch all clinics with the data needed for the recipe
    try:
        # Add the new 'general_dentistry' column to the selection
        columns_to_select = "id, name, address, township, general_dentistry, " + ", ".join(SERVICE_COLUMNS + list(SENTIMENT_MAPPING.keys()))
        response = supabase.table("clinics_data").select(columns_to_select).execute()
        
        if not response.data:
            print("No clinics found. Exiting."); return
        
        clinics = response.data
        total_clinics = len(clinics)
        print(f"Found {total_clinics} clinics to process.")
    except Exception as e:
        print(f"Error fetching clinics: {e}"); return
    
    # 2. Process each clinic
    for i, clinic in enumerate(clinics):
        clinic_id = clinic['id']
        clinic_name = clinic['name']
        
        print(f"\n[{i+1}/{total_clinics}] Processing: {clinic_name} (ID: {clinic_id})")
        
        # 3. Build the new, standardized services_text
        specialized_services = [col.replace('_', ' ') for col in SERVICE_COLUMNS if clinic.get(col) is True]
        
        if clinic.get('general_dentistry') is True:
            # Use the rich, consistent text for general services
            services_text = "a range of general and preventative dental services, including routine check-ups, professional cleaning, scaling, and tooth extractions"
            if specialized_services:
                services_text += ". Specialized services offered include: " + ", ".join(specialized_services)
            else:
                services_text += "."
        else:
            # Fallback for clinics that might not offer general services
            services_text = "specialized services such as " + ", ".join(specialized_services) if specialized_services else "specific dental treatments"

        # 4. Build the list of strengths from sentiment scores (logic is unchanged)
        strengths = []
        for col, text in SENTIMENT_MAPPING.items():
            if clinic.get(col) and clinic.get(col) >= 8.0:
                strengths.append(text)
        strengths_text = ", ".join(strengths) if strengths else "providing a solid patient experience"

        # 5. Create the new, holistic text content to be embedded
        content_to_embed = f"""
        Clinic Name: {clinic.get('name', '')}.
        Location: {clinic.get('address', '')}, in the {clinic.get('township', '')} area.
        This clinic offers {services_text}
        Based on patient reviews, this clinic is known for {strengths_text}.
        """
        
        # 6. Generate the new embedding from Gemini
        try:
            print("  - Generating new embedding from Gemini...")
            embedding_response = genai.embed_content(
                model=embedding_model,
                content=content_to_embed,
                task_type="RETRIEVAL_DOCUMENT",
                title=clinic_name,
                output_dimensionality=768
            )
            new_embedding = embedding_response['embedding']
        except Exception as e:
            print(f"  - ERROR generating embedding for '{clinic_name}': {e}")
            continue

        # 7. Save the new embedding to Supabase
        try:
            print("  - Saving new embedding to Supabase...")
            update_response = supabase.table("clinics_data").update({'embedding': new_embedding}).eq('id', clinic_id).execute()
            
            if update_response.data:
                print(f"  -> SUCCESS: Embedding for '{clinic_name}' has been rebuilt and saved.")
            else:
                # This part is improved to show the actual error from Supabase if available
                error_message = "Unknown error"
                if hasattr(update_response, 'error') and update_response.error:
                    error_message = update_response.error.message
                print(f"  - WARNING: Update for '{clinic_name}' failed. Reason: {error_message}")
        except Exception as e:
            print(f"  - ERROR saving embedding for '{clinic_name}': {e}")

        # Adding a slightly longer sleep to be safe with API rate limits
        time.sleep(1.2) 
        
    print("\n--- Standardized embedding rebuild process complete! ---")

if __name__ == "__main__":
    rebuild_all_embeddings()