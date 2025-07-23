import os
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client
import time
import json

# Simulated function
def fetch_reviews_from_google_places(clinic_name, num_reviews_to_fetch):
    print(f"--- SIMULATING Google Places API call for '{clinic_name}'...")
    return [f"Review {i+1} for {clinic_name}: A placeholder review." for i in range(num_reviews_to_fetch)]

# --- Configuration ---
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
analysis_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Main Logic ---
def analyze_clinic_sentiments():
    print("Starting sentiment analysis process...")
    try:
        clinics_response = supabase.table("clinics_data").select("id, name, reviews").execute()
        clinics = [c for c in clinics_response.data if c.get('reviews') and c['reviews'] > 0]
        total_reviews_population = sum(c['reviews'] for c in clinics)
        print(f"Found {len(clinics)} clinics with a total of {total_reviews_population} reviews.")
    except Exception as e:
        print(f"Error fetching clinics: {e}"); return

    TOTAL_SAMPLE_SIZE = 378
    
    for clinic in clinics:
        clinic_id = clinic['id']
        clinic_name = clinic['name']
        review_count = clinic['reviews']
        proportion = review_count / total_reviews_population
        num_reviews_to_fetch = max(1, round(proportion * TOTAL_SAMPLE_SIZE))
        
        print(f"\nProcessing '{clinic_name}' (ID: {clinic_id})...")
        review_texts = fetch_reviews_from_google_places(clinic_name, num_reviews_to_fetch)
        if not review_texts: continue

        all_scores = []
        for review_text in review_texts:
            prompt = "Analyze the review and provide a score from 1-10 for each aspect. If an aspect is not mentioned, score it -1. Respond ONLY with a valid JSON object. Review: \"{review_text}\" JSON Format: {{\"sentiment_overall\": <score>, \"sentiment_dentist_skill\": <score>, \"sentiment_pain_management\": <score>, \"sentiment_cost_value\": <score>, \"sentiment_staff_service\": <score>, \"sentiment_ambiance_cleanliness\": <score>, \"sentiment_convenience\": <score>}}"
            try:
                response = analysis_model.generate_content(prompt.format(review_text=review_text))
                scores = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
                all_scores.append(scores)
                time.sleep(1)
            except Exception as e:
                print(f"  - Error analyzing review: {e}")
        
        if all_scores:
            avg_scores = {key: round(sum(s[key] for s in all_scores if s.get(key, -1) != -1) / len([s for s in all_scores if s.get(key, -1) != -1]), 2) for key in all_scores[0] if len([s for s in all_scores if s.get(key, -1) != -1]) > 0}
            
            # We now use the reliable .rpc() method to call our function
            try:
                supabase.rpc('update_sentiments', {
                    'clinic_id_to_update': clinic_id,
                    's_overall': avg_scores.get('sentiment_overall'),
                    's_skill': avg_scores.get('sentiment_dentist_skill'),
                    's_pain': avg_scores.get('sentiment_pain_management'),
                    's_cost': avg_scores.get('sentiment_cost_value'),
                    's_staff': avg_scores.get('sentiment_staff_service'),
                    's_ambiance': avg_scores.get('sentiment_ambiance_cleanliness'),
                    's_convenience': avg_scores.get('sentiment_convenience')
                }).execute()
                print(f"-> Successfully called update function for '{clinic_name}'.")
            except Exception as e:
                print(f"  - AN ERROR OCCURRED while calling update function for '{clinic_name}': {e}")

if __name__ == "__main__":
    analyze_clinic_sentiments()