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

# The "Triage" Planner is now simpler, focusing on hard facts
class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating if specified.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of specific, specialized dental services if explicitly named by the user from the known list.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km).")

# --- FastAPI App ---
app = FastAPI()
@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: AI QUERY "TRIAGE" PLANNER
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
    
    # STAGE 2: THE NEW "TWO-PATH" SEARCH LOGIC
    candidate_clinics = []
    
    # Path 1: "Specific Procedure" Search (Hybrid Search)
    if filters.get('services'):
        print("Specific service detected. Running Hybrid Search...")
        query_builder = supabase.table('clinics_data').select('*')
        # Apply all available hard filters
        for service in filters['services']:
            query_builder = query_builder.eq(service, True)
        if filters.get('township'):
            query_builder = query_builder.ilike('address', f"%{filters['township']}%")
        if filters.get('min_rating'):
            query_builder = query_builder.gte('rating', filters['min_rating'])
        if filters.get('max_distance'):
            query_builder = query_builder.lte('distance', filters['max_distance'])
        
        db_response = query_builder.execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from Hybrid Search.")

    # Path 2: "General Query" Search (Semantic-First, then Rank)
    else:
        print("General query detected. Running Semantic-First Search...")
        # Step A: Semantic Search
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)
        query_embedding = query_embedding_response['embedding']
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 20}).execute()
        semantic_candidates = db_response.data if db_response.data else []
        print(f"Found {len(semantic_candidates)} candidates from Semantic Search.")
        
        # Step B: Apply any non-service filters (like location) to the semantic results
        if filters:
            filtered_candidates = []
            for clinic in semantic_candidates:
                match = True
                if filters.get('township') and filters.get('township').lower() not in clinic.get('address', '').lower():
                    match = False
                # Add any other non-service filters here
                if match:
                    filtered_candidates.append(clinic)
            candidate_clinics = filtered_candidates
        else:
            candidate_clinics = semantic_candidates
        print(f"Found {len(candidate_clinics)} candidates after applying filters to semantic results.")


    # STAGE 3: FINAL RANKING
    top_5_clinics = []
    if candidate_clinics:
        # For general queries, rank by quality and convenience
        if not filters.get('services'):
            ranked_clinics = sorted(candidate_clinics, key=lambda x: (x.get('sentiment_overall', 0) or 0, x.get('sentiment_convenience', 0) or 0, x.get('rating', 0) or 0), reverse=True)
        # For specific queries, rank by semantic similarity
        else:
            query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)['embedding']
            for clinic in candidate_clinics:
                if clinic.get('embedding'):
                    db_embedding = json.loads(clinic['embedding'])
                    clinic['similarity'] = np.dot(query_embedding, db_embedding) / (norm(query_embedding) * norm(db_embedding))
                else: clinic['similarity'] = 0
            ranked_clinics = sorted(candidate_clinics, key=lambda x: x.get('similarity', 0), reverse=True)
        
        top_5_clinics = ranked_clinics[:5]

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the best matches I found for your request:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Location: {clinic.get('address')}. Rating: {clinic.get('rating')} stars. Key Sentiments -> Overall: {clinic.get('sentiment_overall')}, Convenience: {clinic.get('sentiment_convenience')}, Skill: {clinic.get('sentiment_dentist_skill')}.\n"
    else:
        context = "I could not find any clinics that matched your search criteria in the database."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your goal is to provide a helpful, data-driven recommendation based ONLY on the context provided.
    Synthesize the data into a conversational answer. Explain WHY the clinics are a good match.
    If the context is empty, politely state that no matches were found.
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}