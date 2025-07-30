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
embedding_model = 'models/gemini-embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel): message: str
class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating if specified by the user.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of specific, specialized dental services if explicitly named by the user from the known list.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km) if specified.")

# <<< The Comprehensive "Trigger Word" Dictionary >>>
GENERAL_CARE_TRIGGERS = [
    "cleaning", "check-up", "checkup", "x-ray", "scaling", "polishing", "fluoride",
    "sealants", "examination", "hygiene", "screening", "prophylaxis", "bitewing",
    "panoramic", "assessment", "maintenance", "general", "routine", "basic"
]

# --- FastAPI App ---
app = FastAPI()
@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: THE "TWO BRAINS" PLANNER
    filters = {}
    try:
        response = planner_model.generate_content(query.message, tools=[SearchFilters])
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            function_call = response.candidates[0].content.parts[0].function_call
            if function_call:
                args = function_call.args
                filters = {k: v for k, v in args.items() if v is not None and v != []}
        print(f"Factual Brain extracted: {filters}")
    except Exception as e:
        print(f"Factual Brain Error: {e}."); filters = {}
        
    ranking_priority = []
    try:
        ranking_prompt = f"""
        Analyze the user's query to determine their qualitative priorities for choosing a dental clinic.
        Return a JSON list of the most important sentiment columns to rank by, in order of priority.
        The available columns are: "sentiment_dentist_skill", "sentiment_pain_management", "sentiment_cost_value", "sentiment_staff_service", "sentiment_ambiance_cleanliness", "sentiment_convenience".
        For "quality", prioritize "sentiment_dentist_skill". For "convenience", prioritize "sentiment_convenience". For "value" or "price", prioritize "sentiment_cost_value".
        USER QUERY: "{query.message}"
        """
        response = ranking_model.generate_content(ranking_prompt)
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        ranking_priority = json.loads(json_text)
        print(f"Semantic Brain determined ranking priority: {ranking_priority}")
    except Exception as e:
        print(f"Semantic Brain Error: {e}."); ranking_priority = []

    # STAGE 2: THE "THREE-PATH" SEARCH LOGIC
    candidate_clinics = []
    user_query_lower = query.message.lower()
    is_general_query = any(word in user_query_lower for word in GENERAL_CARE_TRIGGERS)

    # Path A: "Specific Procedure" Search (Filter-then-Rank)
    if filters.get('services'):
        print("Path A: Specific service detected. Running Filter-then-Rank...")
        query_builder = supabase.table('clinics_data').select('*')
        for service in filters['services']: query_builder = query_builder.eq(service, True)
        if filters.get('township'): query_builder = query_builder.ilike('address', f"%{filters['township']}%")
        db_response = query_builder.execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from Hybrid Search.")
        if candidate_clinics:
            query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)['embedding']
            for clinic in candidate_clinics:
                if clinic.get('embedding'):
                    db_embedding = json.loads(clinic['embedding'])
                    clinic['similarity'] = np.dot(query_embedding, db_embedding) / (norm(query_embedding) * norm(db_embedding))
                else: clinic['similarity'] = 0
            candidate_clinics = sorted(candidate_clinics, key=lambda x: x.get('similarity', 0), reverse=True)

    # Path B: "General Care" Search (Common Sense)
    elif is_general_query:
        print("Path B: General care query detected. Running Common Sense Search...")
        query_builder = supabase.table('clinics_data').select('*')
        if filters.get('township'): query_builder = query_builder.ilike('address', f"%{filters['township']}%")
        db_response = query_builder.execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates for general ranking.")

    # Path C: "Pure Semantic" Fallback
    else:
        print("Path C: Abstract query detected. Running Pure Semantic Fallback...")
        try:
            query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)
            query_embedding = query_embedding_response['embedding']
            db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 25}).execute()
            candidate_clinics = db_response.data if db_response.data else []
            print(f"Found {len(candidate_clinics)} candidates from Semantic Search.")
        except Exception as e:
            print(f"Semantic search DB function error: {e}")

    # STAGE 3: FINAL DYNAMIC RANKING
    top_5_clinics = []
    if candidate_clinics:
        if not ranking_priority:
            ranking_priority = ['sentiment_overall', 'rating', 'reviews']
        else:
            ranking_priority.extend(['rating', 'reviews'])
        ranking_priority = list(dict.fromkeys(ranking_priority))
        print(f"Final dynamic ranking priority: {ranking_priority}")
        ranked_clinics = sorted(candidate_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in ranking_priority), reverse=True)
        top_5_clinics = ranked_clinics[:5]

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the best matches I found for your request:\n"
        for clinic in top_5_clinics:
            services_offered = [col.replace('_', ' ') for col in ServiceEnum if clinic.get(col) is True]
            services_text = f"Services offered: {', '.join(services_offered)}." if services_offered else ""
            context += f"- **{clinic.get('name')}**\n  - **Location:** {clinic.get('address')}\n  - **Rating:** {clinic.get('rating')} stars\n  - **Key Sentiments:** Overall: {clinic.get('sentiment_overall')}, Skill: {clinic.get('sentiment_dentist_skill')}, Convenience: {clinic.get('sentiment_convenience')}\n"
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria in the database."

    # <<< The "Forced Formatting" and Conditional Caveat Prompt >>>
    distance_rule = ""
    if filters.get('max_distance') or "km" in query.message.lower() or "distance" in query.message.lower():
        distance_rule = "IMPORTANT RULE: You MUST append the following sentence to the VERY END of your response, on a new line: \"(Please note: all distances are measured from the Johor Bahru CIQ complex.)\""

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your goal is to provide a helpful, data-driven recommendation based ONLY on the context provided.
    Synthesize the data into a conversational answer. Explain WHY the clinics are a good match for the user's specific priorities.
    
    **CRITICAL FORMATTING RULE: You MUST structure your response for maximum readability. Use a clear introductory sentence. Then, for each recommended clinic, start a new paragraph with the clinic's name in bold. Use bullet points or indented lines for key data like rating and specific sentiment scores.**
    
    You must correctly interpret NULL/None values. If a sentiment score is not present, state that 'a specific score was not available'.
    {distance_rule}
    
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}