import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional
import json
import numpy as np
from numpy.linalg import norm

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- AI Models ---
factual_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
ranking_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel):
    message: str

class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="If the user mentions a specific dental service, extract it. Map common terms to the enum value (e.g., 'implants' -> 'dental_implant', 'cap' -> 'dental_crown').")
    township: Optional[str] = Field(None, description="If the user mentions a specific township or area, extract the name of the location.")

# --- FastAPI App ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: DUAL-STREAM BRAIN ANALYSIS
    filters = {}
    ranking_priorities = []
    
    try:
        factual_response = factual_brain_model.generate_content(
            f"Extract entities from the user's query based on the tool schema. Query: '{query.message}'",
            tools=[UserIntent]
        )
        function_call = factual_response.candidates[0].content.parts[0].function_call
        if function_call:
            args = function_call.args
            if args.get('service'):
                filters['services'] = [args.get('service')]
            if args.get('township'):
                filters['township'] = args.get('township')
        print(f"Factual Brain extracted filters: {filters}")
    except Exception as e:
        print(f"Factual Brain Error: {e}.")
        filters = {}

    try:
        ranking_prompt = f"""
        Analyze the user's query to determine their sentimental priorities for ranking clinics.
        The available priorities are: 'sentiment_dentist_skill', 'sentiment_cost_value', 'sentiment_convenience', 'sentiment_pain_management'.
        - If the user explicitly mentions a priority (e.g., 'good value', 'high quality'), return a ranked list of the corresponding column names.
        - If the user mentions a specific service, infer the most likely priority (e.g., 'implants' implies 'sentiment_dentist_skill', 'whitening' implies 'sentiment_cost_value').
        - If the query is general (e.g., 'good dentist'), return an empty list.
        Return a single JSON list of strings.
        Query: "{query.message}"
        """
        ranking_response = ranking_brain_model.generate_content(ranking_prompt)
        json_text = ranking_response.text.strip().replace("```json", "").replace("```", "")
        ranking_priorities = json.loads(json_text)
        print(f"Ranking Brain determined priorities: {ranking_priorities}")
    except Exception as e:
        print(f"Ranking Brain Error: {e}.")
        ranking_priorities = []

    # STAGE 2: ROBUST SEMANTIC SEARCH
    candidate_clinics = []
    print("Performing initial semantic search...")
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
        query_embedding_list = query_embedding_response['embedding']
        
        # Convert the list to the string format that the new Supabase function expects
        query_embedding_text = "[" + ",".join(map(str, query_embedding_list)) + "]"

        # Call the RPC function with the text version of the embedding
        db_response = supabase.rpc('match_clinics_simple', {
            'query_embedding_text': query_embedding_text, 
            'match_count': 75
        }).execute()
        
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: FILTERING AND DYNAMIC RANKING
    qualified_clinics = []
    if candidate_clinics:
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                qualified_clinics.append(clinic)
        print(f"Found {len(qualified_clinics)} candidates after applying Quality Gate.")

        if filters:
            factually_filtered_clinics = []
            for clinic in qualified_clinics:
                match = True
                if filters.get('township') and filters.get('township').lower() not in clinic.get('address', '').lower():
                    match = False
                if filters.get('services'):
                    for service in filters.get('services'):
                        if not clinic.get(service, False):
                            match = False
                            break
                if match:
                    factually_filtered_clinics.append(clinic)
            qualified_clinics = factually_filtered_clinics
            print(f"Found {len(qualified_clinics)} candidates after applying Factual Filters.")

    top_clinics = []
    if qualified_clinics:
        # The Decision Engine for Ranking
        if ranking_priorities:
            print(f"Applying SENTIMENT-FIRST ranking with priorities: {ranking_priorities}")
            ranking_keys = ranking_priorities + ['rating', 'reviews']
            ranking_keys = list(dict.fromkeys(ranking_keys))
            ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in ranking_keys), reverse=True)
        else:
            print("Applying OBJECTIVE-FIRST weighted score.")
            max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
            for clinic in qualified_clinics:
                norm_rating = (clinic.get('rating', 0) - 1) / 4.0
                norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
                clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
            ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
        
        top_clinics = ranked_clinics[:3]
        print(f"Ranking complete. Top clinic: {top_clinics[0]['name'] if top_clinics else 'N/A'}")

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_clinics:
        clinic_data_for_prompt = []
        for clinic in top_clinics:
            clinic_info = {
                "name": clinic.get('name'), "address": clinic.get('address'),
                "rating": clinic.get('rating'), "reviews": clinic.get('reviews'),
                "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),
            }
            clinic_data_for_prompt.append(clinic_info)
        context = json.dumps(clinic_data_for_prompt, indent=2)
    else:
        context = "I'm sorry, I could not find any clinics that matched your specific search criteria after applying our quality standards."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your task is to generate a concise, data-driven recommendation based on the provided JSON context. Your response must be friendly, professional, and perfectly formatted like the example.

    **CONTEXT (TOP CLINICS FOUND):**
    ```json
    {context}
    ```
    **--- EXAMPLE OF PERFECT RESPONSE ---**
    Based on your criteria, here are my top recommendations:

    🏆 **Top Choice: JDT Dental**
    *   **Rating:** 4.9★ (1542 reviews)
    *   **Address:** 41B, Jalan Kuning 2, Taman Pelangi, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** An exceptionally high rating combined with a massive number of reviews indicates consistently excellent service.

    🌟 **Excellent Alternatives:**

    **Austin Dental Group (Mount Austin)**
    *   **Rating:** 4.9★ (1085 reviews)
    *   **Address:** 33G, Jalan Mutiara Emas 10/19, Taman Mount Austin, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** Another highly-rated option with a very strong track record and convenient daily hours.
    ---
    
    **MANDATORY RULES:**
    1.  Emulate the tone and structure of the example.
    2.  Use bullet points (`* `) for details.
    3.  Add a blank line between each clinic block.
    4.  Summarize operating hours concisely.
    5.  Keep the "Why it's great" and "My Recommendation" sections brief.
    """
    
    final_response = generation_model.generate_content(augmented_prompt)

    return {"response": final_response.text}