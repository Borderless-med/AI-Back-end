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
# This is the correct, future-proof model
embedding_model = 'models/gemini-embedding-001' 

# --- Define the sentiment columns for the "Simple Recipe" ---
SENTIMENT_MAPPING = {
    'sentiment_dentist_skill': 'highly skilled dentists',
    'sentiment_pain_management': 'gentle and painless treatment',
    'sentiment_cost_value': 'good value for money',
    'sentiment_staff_service': 'friendly and helpful staff',
    'sentiment_ambiance_cleanliness': 'a clean and modern environment',
    'sentiment_convenience': 'convenient and on-time appointments'
}

def generate_sg_embeddings():
    print("Starting the SG Clinic embedding process...")
    
    # Fetch all SG clinics that do not have an embedding yet
    try:
        columns_to_select = "id, name, address, township, " + ", ".join(list(SENTIMENT_MAPPING.keys()))
        response = supabase.table("sg_clinics").select(columns_to_select).filter("embedding", "is", "null").execute()
        
        if not response.data:
            print("All SG clinics are already embedded. Exiting."); return
        
        clinics = response.data
        total_clinics = len(clinics)
        print(f"Found {total_clinics} SG clinics that need to be embedded.")
    except Exception as e:
        print(f"Error fetching SG clinics: {e}"); return
    
    # Process each clinic
    for i, clinic in enumerate(clinics):
        clinic_id = clinic['id']
        clinic_name = clinic['name']
        
        print(f"\n[{i+1}/{total_clinics}] Processing: {clinic_name} (ID: {clinic_id})")
        
        # Build the text to be embedded using the recipe
        strengths = []
        for col, text in SENTIMENT_MAPPING.items():
            if clinic.get(col, 0) and clinic.get(col, 0) >= 8.0:
                strengths.append(text)
        strengths_text = ", ".join(strengths) if strengths else "providing a solid patient experience"
        content_to_embed = f"""
        Clinic Name: {clinic.get('name', '')}.
        Location: {clinic.get('address', '')}, in the {clinic.get('township', '')} area.
        This clinic offers a range of general and preventative dental services.
        Based on patient reviews, this clinic is known for {strengths_text}.
        """
        
        # Generate the embedding from Gemini
        try:
            print("  - Generating embedding from Gemini...")
            embedding_response = genai.embed_content(
                model=embedding_model,
                content=content_to_embed,
                task_type="RETRIEVAL_DOCUMENT",
                title=clinic_name,
                # --- THE DEFINITIVE FIX ---
                # This instruction forces the model to create a 768-dimension vector, matching the database.
                output_dimensionality=768
            )
            new_embedding = embedding_response['embedding']
        except Exception as e:
            print(f"  - ERROR generating embedding for '{clinic_name}': {e}")
            continue

        # Save the new embedding to Supabase
        try:
            print("  - Saving new embedding to Supabase...")
            # Use the RPC helper function, which is the most robust method
            supabase.rpc('update_clinic_embedding', {
                'clinic_id_to_update': clinic_id,
                'new_embedding': new_embedding
            }).execute()
            print(f"  -> SUCCESS: Embedding for '{clinic_name}' has been saved.")
        except Exception as e:
            print(f"  - ERROR saving embedding for '{clinic_name}': {e}")

        time.sleep(1.2)
        
    print("\n--- SG Clinic embedding process complete! ---")

if __name__ == "__main__":
    generate_sg_embeddings()