import os
import time
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client

# --- Load environment variables and configure clients ---
load_dotenv()

# Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# Google AI
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
# Use the embedding-specific model
embedding_model = 'models/embedding-001'

print("Fetching all clinics from the 'clinics_data' table...")

try:
    # 1. FETCH ALL CLINICS
    response = supabase.table("clinics_data").select("id, name, address, township, dentist, rating, reviews, tooth_filling, root_canal, dental_crown, dental_implant, teeth_whitening").execute()
    
    if not response.data:
        print("No clinics found. Please check your table.")
    else:
        clinics = response.data
        total_clinics = len(clinics)
        print(f"Successfully fetched {total_clinics} clinics.")

        # 2. PROCESS EACH CLINIC
        for i, clinic in enumerate(clinics):
            clinic_id = clinic['id']
            
            # We create a rich text description for each clinic
            # This combines all the important data into one block of text for the AI
            content_to_embed = f"""
            Clinic Name: {clinic.get('name', '')}.
            Address: {clinic.get('address', '')}, {clinic.get('township', '')}.
            Dentist: {clinic.get('dentist', '')}.
            Google Rating: {clinic.get('rating', 'N/A')} stars with {clinic.get('reviews', 'N/A')} reviews.
            Services offered include: 
            {'tooth filling' if clinic.get('tooth_filling') else ''}, 
            {'root canal treatment' if clinic.get('root_canal') else ''}, 
            {'dental crowns' if clinic.get('dental_crown') else ''}, 
            {'dental implants' if clinic.get('dental_implant') else ''}, 
            {'teeth whitening' if clinic.get('teeth_whitening') else ''}.
            """
            
            # 3. GENERATE THE EMBEDDING
            print(f"[{i+1}/{total_clinics}] Generating embedding for: {clinic['name']}...")
            embedding_response = genai.embed_content(
                model=embedding_model,
                content=content_to_embed,
                task_type="RETRIEVAL_DOCUMENT", # Important for search-quality embeddings
                title=clinic['name']
            )
            embedding = embedding_response['embedding'] # This is the list of numbers

            # 4. SAVE THE EMBEDDING BACK TO SUPABASE
            # We update the specific row using its unique 'id'
            supabase.table("clinics_data").update({'embedding': embedding}).eq('id', clinic_id).execute()
            
            print(f"-> Successfully saved embedding for {clinic['name']}.")
            
            # We add a small delay to respect API rate limits
            time.sleep(1) 

        print("\n--- All clinics have been successfully indexed! ---")

except Exception as e:
    print(f"\nAn error occurred: {e}")