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
embedding_model = 'models/gemini-embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel): message: str
class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating, e.g., 4.5.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of all specific dental services if and only if the user explicitly names them from the known list.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km).")
    # These are now used to guide the ranking, not just filter
    min_dentist_skill: float = Field(None, description="For queries about 'best skill' or 'professional' dentists, set this to 8.0.")
    min_pain_management: float = Field(None, description="For queries about 'painless' or 'gentle' treatment, set this to 8.0.")
    min_cost_value: float = Field(None, description="For queries about 'cheap', 'affordable', or 'good value', set this to 7.5.")
    min_staff_service: float = Field(None, description="For queries about 'friendly staff' or 'good service', set this to 8.0.")
    min_ambiance_cleanliness: float = Field(None, description="For queries about 'clean' or 'modern' clinics, set this to 8.0.")
    min_convenience: float = Field(None, description="For queries about 'on time' or 'easy booking', set this to 8.0.")


# --- FastAPI App ---
app = FastAPI()
@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: AI QUERY PLANNER
    filters = {}
    try:
        response = planner_model.generate_content(query.message, tools=[SearchFilters])
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            function_call = response.candidates[0].content.parts[0].function_call
            if function_call:
                args = function_call.args
                filters = {k: v for k, v in args.items() if v is not None}
        print(f"AI-extracted factual filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}
    
    # STAGE 2: "SEMANTIC-FIRST" SEARCH
    candidate_clinics = []
    
    print("Performing initial semantic search...")
    query_embedding_response = genai.embed_content(
        model=embedding_model,
        content=query.message,
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=768
    )
    query_embedding = query_embedding_response['embedding']
    
    try:
        db_response = supabase.rpc('match_clinics_simple', {
            'query_embedding': query_embedding,
            'match_count': 25
        }).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: FACTUAL FILTERING AND DYNAMIC RANKING
    final_candidates = []
    if candidate_clinics:
        active_filters = {k: v for k, v in filters.items() if v is not None}
        
        if active_filters:
            for clinic in candidate_clinics:
                match = True
                if active_filters.get('township') and active_filters.get('township').lower() not in clinic.get('address', '').lower(): match = False
                if active_filters.get('min_rating') and (clinic.get('rating') is None or clinic.get('rating', 0) < active_filters.get('min_rating')): match = False
                if active_filters.get('services'):
                    for service in active_filters.get('services'):
                        if not clinic.get(service, False): match = False; break
                if active_filters.get('max_distance') and (clinic.get('distance') is None or clinic.get('distance', 999) > active_filters.get('max_distance')): match = False
                
                if match:
                    final_candidates.append(clinic)
        else:
            final_candidates = candidate_clinics
    
    print(f"Found {len(final_candidates)} candidates after applying factual filters.")
    
    # UPGRADE #1: The "Dynamic Ranking" Brain
    if final_candidates:
        ranking_priority = []
        if filters.get('min_convenience'): ranking_priority.append('sentiment_convenience')
        if filters.get('min_dentist_skill'): ranking_priority.append('sentiment_dentist_skill')
        if filters.get('min_pain_management'): ranking_priority.append('sentiment_pain_management')
        if filters.get('min_cost_value'): ranking_priority.append('sentiment_cost_value')
        if filters.get('min_staff_service'): ranking_priority.append('sentiment_staff_service')
        
        if not ranking_priority:
            ranking_priority = ['sentiment_overall', 'sentiment_dentist_skill', 'rating', 'reviews']
        else:
            ranking_priority.extend(['sentiment_overall', 'rating', 'reviews'])

        print(f"Dynamic ranking priority: {ranking_priority}")
        
        ranked_clinics = sorted(final_candidates, key=lambda x: tuple(x.get(key, 0) or 0 for key in ranking_priority), reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the best matches I found for your request:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Location: {clinic.get('address')}, Rating: {clinic.get('rating')} stars. Key Sentiments -> Overall: {clinic.get('sentiment_overall')}, Convenience: {clinic.get('sentiment_convenience')}, Skill: {clinic.get('sentiment_dentist_skill')}.\n"
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria in the database."

    # UPGRADE #2: The "Clarity" Upgrade
    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your goal is to provide a helpful, data-driven recommendation based ONLY on the context provided.
    Synthesize the data into a conversational answer. Explain WHY the clinics are a good match for the user's specific priorities.
    
    **CRITICAL FORMATTING RULE: You MUST structure your response for maximum readability. Use a clear introductory sentence. Then, for each recommended clinic, start a new paragraph with the clinic's name in bold. Use bullet points within each paragraph to list key data like rating and specific sentiment scores.**
    
    If the context is empty, politely state that no matches were found.
    You must correctly interpret NULL/None values. If a sentiment score is not present, state that 'a specific score was not available'.
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}