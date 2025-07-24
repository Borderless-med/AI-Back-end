import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
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
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel): message: str
class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating. For 'highly-rated' or 'best', use 4.5.")
    service: ServiceEnum = Field(None, description="Extract the specific dental service requested.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km).")
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
                service_value = args.get("service")
                filters = {
                    "township": args.get("township"), "min_rating": args.get("min_rating"),
                    "service": service_value.value if isinstance(service_value, Enum) else service_value,
                    "max_distance": args.get("max_distance"), "min_dentist_skill": args.get("min_dentist_skill"),
                    "min_pain_management": args.get("min_pain_management"), "min_cost_value": args.get("min_cost_value"),
                    "min_staff_service": args.get("min_staff_service"),
                    "min_ambiance_cleanliness": args.get("min_ambiance_cleanliness"),
                    "min_convenience": args.get("min_convenience")
                }
        print(f"AI-extracted filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}
    
    # STAGE 2: DATABASE QUERY (with new Fallback Logic)
    all_candidates = {} # Use a dictionary to store unique clinics by ID
    active_filters = {k: v for k, v in filters.items() if v is not None}

    # Helper function to run queries and add unique results
    def run_query(query_builder, source_name):
        try:
            db_response = query_builder.execute()
            candidates = db_response.data if db_response.data else []
            print(f"Found {len(candidates)} candidates from '{source_name}' search.")
            for clinic in candidates:
                if clinic['id'] not in all_candidates:
                    all_candidates[clinic['id']] = clinic
        except Exception as e:
            print(f"Database query error for '{source_name}': {e}")

    # Query 1: The "Ideal" Strict Search
    query_builder_ideal = supabase.table('clinics_data').select('*')
    for key, value in active_filters.items():
        if key == 'township': query_builder_ideal = query_builder_ideal.ilike('address', f"%{value}%")
        elif key == 'min_rating': query_builder_ideal = query_builder_ideal.gte('rating', value)
        elif key == 'service': query_builder_ideal = query_builder_ideal.eq(value, True)
        elif key == 'max_distance': query_builder_ideal = query_builder_ideal.lte('distance', value)
        elif key.startswith('min_'):
            db_column = key.replace('min_', 'sentiment_')
            query_builder_ideal = query_builder_ideal.gte(db_column, value)
    run_query(query_builder_ideal, "Ideal")

    # Fallback Logic: If the ideal search is too narrow, broaden it
    if len(all_candidates) < 3:
        print("Ideal search returned few results. Trying fallbacks...")
        
        # Fallback A: Relax sentiment filters, search by location and service
        if active_filters.get('township') or active_filters.get('service'):
            query_fallback_A = supabase.table('clinics_data').select('*')
            if active_filters.get('township'): query_fallback_A = query_fallback_A.ilike('address', f"%{active_filters.get('township')}%")
            if active_filters.get('service'): query_fallback_A = query_fallback_A.eq(active_filters.get('service'), True)
            run_query(query_fallback_A, "Fallback A - Location/Service")

        # Fallback B: Relax location, search by key sentiment
        key_sentiment_filters = ['min_pain_management', 'min_dentist_skill', 'min_staff_service']
        query_fallback_B = supabase.table('clinics_data').select('*')
        key_filter_applied = False
        for key in key_sentiment_filters:
            if active_filters.get(key):
                db_column = key.replace('min_', 'sentiment_')
                query_fallback_B = query_fallback_B.gte(db_column, active_filters.get(key))
                key_filter_applied = True
        if key_filter_applied:
            run_query(query_fallback_B, "Fallback B - Key Sentiment")

    candidate_clinics = list(all_candidates.values())
    print(f"Found a total of {len(candidate_clinics)} unique candidates after all searches.")

    # STAGE 3: SEMANTIC RANKING
    if candidate_clinics:
        query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")['embedding']
        for clinic in candidate_clinics:
            if clinic.get('embedding'):
                db_embedding = json.loads(clinic['embedding'])
                clinic['similarity'] = np.dot(query_embedding, db_embedding) / (norm(query_embedding) * norm(db_embedding))
            else: clinic['similarity'] = 0
        ranked_clinics = sorted(candidate_clinics, key=lambda x: x.get('similarity', 0), reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the most relevant clinics I found based on your request:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Address: {clinic.get('address')}, Rating: {clinic.get('rating')} stars. Sentiments -> Skill: {clinic.get('sentiment_dentist_skill')}, Pain: {clinic.get('sentiment_pain_management')}, Staff: {clinic.get('sentiment_staff_service')}, Value: {clinic.get('sentiment_cost_value')}.\n"
    else:
        context = "I could not find any clinics in the database that matched your specific criteria, even after broadening my search."

    augmented_prompt = f"""
    You are a helpful assistant. Answer the user's question based ONLY on the context. Summarize the findings in a conversational way, explaining why each option is a good choice.
    IMPORTANT RULE: If the user's question or the context mentions distance, you MUST append this sentence to the VERY END of your response, on a new line:
    "(Please note: all distances are measured from the Johor Bahru CIQ complex.)"
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}