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

# --- Define the full list of boolean service columns ---
SERVICE_COLUMNS = [
    'tooth_filling', 'root_canal', 'dental_crown', 'dental_implant', 'wisdom_tooth',
    'gum_treatment', 'dental_bonding', 'inlays_onlays', 'teeth_whitening',
    'composite_veneers', 'porcelain_veneers', 'enamel_shaping', 'braces',
    'gingivectomy', 'bone_grafting', 'sinus_lift', 'frenectomy', 'tmj_treatment',
    'sleep_apnea_appliances', 'crown_lengthening', 'oral_cancer_screening', 'alveoplasty'
]

def rebuild_all_embeddings():
    print("Starting the COMPREHENSIVE embedding rebuild process...")
    
    # 1. Fetch all clinics with the data needed for the recipe
    try:
        # We select the core identifiers plus all of our service columns
        columns_to_select = "id, name, address, township, " + ", ".join(SERVICE_COLUMNS)
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
        
        # 3. Build the list of services this clinic offers
        services_offered = []
        for service_col in SERVICE_COLUMNS:
            if clinic.get(service_col) is True:
                # Convert 'dental_implant' to 'dental implant' for better semantic meaning
                human_readable_service = service_col.replace('_', ' ')
                services_offered.append(human_readable_service)
        
        services_text = ", ".join(services_offered) if services_offered else "basic dental services"

        # 4. Create the rich, comprehensive text content to be embedded
        content_to_embed = f"""
        Clinic Name: {clinic.get('name', '')}.
        Location: {clinic.get('address', '')}, in the {clinic.get('township', '')} area.
        Key Services Offered: {services_text}.
        """
        
        # 5. Generate the new embedding from Gemini
        try:
            print("  - Generating new embedding from Gemini...")
            embedding_response = genai.embed_content(
                model=embedding_model,
                content=content_to_embed,
                task_type="RETRIEVAL_DOCUMENT",
                title=clinic_name
            )
            new_embedding = embedding_response['embedding']
        except Exception as e:
            print(f"  - ERROR generating embedding for '{clinic_name}': {e}")
            continue

        # 6. Save the new embedding to Supabase
        try:
            print("  - Saving new embedding to Supabase...")
            update_response = supabase.table("clinics_data").update({'embedding': new_embedding}).eq('id', clinic_id).execute()
            
            if update_response.data:
                print(f"  -> SUCCESS: Embedding for '{clinic_name}' has been rebuilt.")
            else:
                print(f"  - WARNING: Update for '{clinic_name}' failed silently.")
        except Exception as e:
            print(f"  - ERROR saving embedding for '{clinic_name}': {e}")

        time.sleep(1) # Respect API rate limits
        
    print("\n--- Comprehensive embedding rebuild process complete! ---")

if __name__ == "__main__":
    rebuild_all_embeddings()