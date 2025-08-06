import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List
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
planner_model = genai.GenerativeModel('gemini-1.5-flash-latest')
ranking_model = genai.GenerativeModel('gemini-1.5-flash-latest') 
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel):
    message: str

class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating if specified by the user.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of specific, specialized dental services if explicitly named by the user from the known list.")

# --- FastAPI App ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: FACTUAL BRAIN
    filters = {}
    
    # STAGE 2: SEMANTIC SEARCH
    candidate_clinics = []
    print("Performing initial semantic search with a wider net...")
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
        query_embedding = query_embedding_response['embedding']
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 75}).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: FILTERING AND RANKING
    qualified_clinics = []
    if candidate_clinics:
        # Step 3A: The Quality Gate Filter
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                qualified_clinics.append(clinic)
        print(f"Found {len(qualified_clinics)} candidates after applying Quality Gate (rating >= 4.5, reviews >= 30).")

    top_clinics = []
    if qualified_clinics:
        # Step 3B: THE WEIGHTED SCORE RANKING
        print("Calculating weighted quality scores...")
        max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
        
        for clinic in qualified_clinics:
            norm_rating = (clinic.get('rating', 0) - 1) / 4.0
            norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
            clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
        
        ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
        # *** KEY CHANGE: Only select the top 3 clinics ***
        top_clinics = ranked_clinics[:3]
        print(f"Ranking complete. Top clinic by weighted score: {top_clinics[0]['name'] if top_clinics else 'N/A'}")


    # STAGE 4: FINAL, CONCISE RESPONSE GENERATION
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
        context = "I'm sorry, I could not find any clinics that matched your search criteria after applying our quality standards."

    # This prompt is now engineered for brevity and clarity.
    augmented_prompt = f"""
    You are an expert, friendly, and concise dental clinic assistant. Your goal is to provide a brief, data-driven recommendation based ONLY on the JSON context provided. You must exactly emulate the formatting shown in the EXAMPLE below.

    **USER'S ORIGINAL QUESTION:**
    {query.message}

    **CONTEXT (TOP CLINICS FOUND IN JSON FORMAT):**
    ```json
    {context}
    ```

    **--- YOUR TASK & STRICT RULES FOR BREVITY ---**

    Synthesize the provided JSON data into a short and highly readable recommendation.

    **--- EXAMPLE OF PERFECT FORMATTING ---**
    Based on your criteria, here are my top recommendations:

    🏆 Top Choice: **CK Dental (Taman Abad)**
    Rating: 5.0★ (294 reviews)
    Address: 320, Jalan Dato Sulaiman, Taman Abad
    Hours: Mon-Fri: 9:30 AM – 6:30 PM, Weekends: 9:30 AM – 5:00 PM
    Why it's great: Perfect 5-star rating with nearly 300 reviews, making it ideal for convenience and quality.

    🌟 Excellent Alternative:
    
    **Asiaa Dental Clinic**
    Rating: 5.0★ (292 reviews)
    Address: 113A, Jalan Perisai, Taman Sri Tebrau
    Hours: Daily: 9:00 AM – 9:00 PM
    Why it's great: Extended operating hours until 9 PM every day offer exceptional convenience!
    
    *(...a blank line would follow here before the next clinic...)*
    ---
    
    **MANDATORY FORMATTING & CONTENT RULES:**
    - Present the top 2-3 clinics only.
    - Use "🏆 Top Choice:" for the first clinic and "🌟 Excellent Alternative:" (or "🌟 Excellent Alternatives:") as a single heading for the rest.
    - You MUST summarize operating hours concisely.
    - The "Why it's great:" justification MUST be a single, brief sentence.
    - **CRITICAL: You MUST place a single blank line between each clinic's full recommendation block.**
    - After the list, include a very brief "💡 My Recommendation:" summary (1-2 sentences only).
    - **DO NOT** include a "Pro Tips" section.
    - End with a friendly, one-line follow-up question.
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}
