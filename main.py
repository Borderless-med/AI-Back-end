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
    min_rating: float = Field(None, description="Extract a minimum Google rating. For 'highly-rated' or 'best', use 4.5.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of all specific dental services if and only if the user explicitly names them from the known list.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km).")

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
            'match_count': 20
        }).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: FACTUAL FILTERING AND RANKING
    final_candidates = []
    if candidate_clinics:
        active_filters = {k: v for k, v in filters.items() if v is not None}
        
        if active_filters:
            for clinic in candidate_clinics:
                match = True
                if active_filters.get('township') and active_filters.get('township').lower() not in clinic.get('address', '').lower():
                    match = False
                if active_filters.get('min_rating') and (clinic.get('rating') is None or clinic.get('rating', 0) < active_filters.get('min_rating')):
                    match = False
                if active_filters.get('services'):
                    for service in active_filters.get('services'):
                        if not clinic.get(service, False):
                            match = False; break
                if active_filters.get('max_distance') and (clinic.get('distance') is None or clinic.get('distance', 999) > active_filters.get('max_distance')):
                    match = False
                
                if match:
                    final_candidates.append(clinic)
        else:
            final_candidates = candidate_clinics
    
    print(f"Found {len(final_candidates)} candidates after applying factual filters.")
    
    if final_candidates:
        ranked_clinics = sorted(final_candidates, key=lambda x: (x.get('sentiment_overall', 0) or 0, x.get('sentiment_dentist_skill', 0) or 0), reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the most relevant clinics I found based on your request:\n"
        for clinic in top_5_clinics:
            # <<< THIS IS THE FINAL, DEFINITIVE FIX >>>
            # Dynamically build the list of services for the context
            services_offered = [col.replace('_', ' ') for col in ServiceEnum if clinic.get(col) is True]
            services_text = f"Services offered: {', '.join(services_offered)}." if services_offered else ""
            
            # Add the complete and rich context line
            context += f"- Name: {clinic.get('name')}, Address: {clinic.get('address')}, Rating: {clinic.get('rating')} stars. {services_text} Key Sentiments -> Skill: {clinic.get('sentiment_dentist_skill')}, Pain: {clinic.get('sentiment_pain_management')}.\n"
    else:
        context = "I could not find any clinics that matched your search criteria."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your goal is to provide the most helpful, data-driven recommendation possible based ONLY on the context provided.
    You must correctly interpret NULL/None values. If a sentiment score is not present, state that 'a specific score was not available'. DO NOT interpret a missing score as a good or bad score.
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}
