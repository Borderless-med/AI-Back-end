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
    township: str = Field(None, description="The township or area, e.g., 'Permas Jaya'.")
    min_rating: float = Field(None, description="The minimum Google rating, e.g., 4.5.")
    service: ServiceEnum = Field(None, description="A specific dental service the user wants.")
    max_distance: float = Field(None, description="The maximum acceptable distance in kilometers from the CIQ.")
    min_dentist_skill: float = Field(None, description="Minimum score for dentist skill (1-10).")
    min_pain_management: float = Field(None, description="Minimum score for pain management (1-10).")
    min_cost_value: float = Field(None, description="Minimum score for value for money (1-10).")
    min_staff_service: float = Field(None, description="Minimum score for staff service (1-10).")
    min_ambiance_cleanliness: float = Field(None, description="Minimum score for ambiance/cleanliness (1-10).")
    min_convenience: float = Field(None, description="Minimum score for convenience (1-10).")

# --- FastAPI App ---
app = FastAPI()
@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # UPGRADE #3: The Engineered Prompt for the AI Planner
    planner_prompt = f"""
    Analyze the user's query and extract appropriate search filters.
    RULES:
    - For 'best', 'highly-rated', or 'good', set a minimum score. Good defaults are 8.0 for skill/staff/pain and 4.5 for Google rating.
    - For 'cheap', 'affordable', or 'good value', set a `min_cost_value` of 7.5.
    - Prioritize extracting a `service` if a dental procedure is mentioned.
    - Respond ONLY with the JSON for the tool.
    USER QUERY: '{query.message}'
    """

    # STAGE 1: AI QUERY PLANNER (with robust error handling)
    filters = {}
    try:
        response = planner_model.generate_content(planner_prompt, tools=[SearchFilters])
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
                    "min_staff_service": args.get("min_staff_service"), "min_ambiance_cleanliness": args.get("min_ambiance_cleanliness"),
                    "min_convenience": args.get("min_convenience")
                }
        print(f"AI-extracted filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}

    # STAGE 2: DATABASE QUERY (with new Fallback Logic)
    all_candidates = {} # Use a dictionary to avoid duplicates
    
    # Helper function for querying
    def run_query(query_builder, source_name):
        try:
            db_response = query_builder.execute()
            candidates = db_response.data if db_response.data else []
            print(f"Found {len(candidates)} candidates from '{source_name}' search.")
            for clinic in candidates:
                all_candidates[clinic['id']] = clinic # Add to dictionary, automatically handles duplicates
        except Exception as e:
            print(f"Database query error for '{source_name}': {e}")

    # Query 1: The "Ideal" Strict Search
    query_builder_ideal = supabase.table('clinics_data').select('*')
    if filters.get('township'): query_builder_ideal = query_builder_ideal.ilike('township', f"%{filters['township']}%")
    if filters.get('min_rating'): query_builder_ideal = query_builder_ideal.gte('rating', filters['min_rating'])
    if filters.get('service'): query_builder_ideal = query_builder_ideal.eq(filters['service'], True)
    if filters.get('max_distance'): query_builder_ideal = query_builder_ideal.lte('distance', filters['max_distance'])
    if filters.get('min_dentist_skill'): query_builder_ideal = query_builder_ideal.gte('sentiment_dentist_skill', filters['min_dentist_skill'])
    # Add all other sentiment filters here...
    if filters.get('min_pain_management'): query_builder_ideal = query_builder_ideal.gte('sentiment_pain_management', filters['min_pain_management'])
    if filters.get('min_cost_value'): query_builder_ideal = query_builder_ideal.gte('sentiment_cost_value', filters['min_cost_value'])
    if filters.get('min_staff_service'): query_builder_ideal = query_builder_ideal.gte('sentiment_staff_service', filters['min_staff_service'])
    if filters.get('min_ambiance_cleanliness'): query_builder_ideal = query_builder_ideal.gte('sentiment_ambiance_cleanliness', filters['min_ambiance_cleanliness'])
    if filters.get('min_convenience'): query_builder_ideal = query_builder_ideal.gte('sentiment_convenience', filters['min_convenience'])
    run_query(query_builder_ideal, "Ideal")
    
    # UPGRADE #2: Fallback Logic
    if len(all_candidates) < 3:
        print("Ideal search returned few results. Trying fallbacks...")
        # Fallback A: Relax sentiment/service, search by location
        if filters.get('township'):
            query_fallback_A = supabase.table('clinics_data').select('*').ilike('township', f"%{filters['township']}%")
            run_query(query_fallback_A, "Fallback A - Location")
        
        # Fallback B: Relax location, search by key service/sentiment
        key_filter_applied = False
        query_fallback_B = supabase.table('clinics_data').select('*')
        if filters.get('service'):
            query_fallback_B = query_fallback_B.eq(filters['service'], True)
            key_filter_applied = True
        if filters.get('min_pain_management'):
            query_fallback_B = query_fallback_B.gte('sentiment_pain_management', filters['min_pain_management'])
            key_filter_applied = True
        if filters.get('min_dentist_skill'):
            query_fallback_B = query_fallback_B.gte('sentiment_dentist_skill', filters['min_dentist_skill'])
            key_filter_applied = True
        
        if key_filter_applied:
            run_query(query_fallback_B, "Fallback B - Key Criteria")

    candidate_clinics = list(all_candidates.values())

    # STAGE 3: SEMANTIC RANKING (remains the same)
    if candidate_clinics:
        query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")['embedding']
        for clinic in candidate_clinics:
            if clinic.get('embedding'):
                db_embedding = json.loads(clinic['embedding'])
                clinic['similarity'] = np.dot(query_embedding, db_embedding) / (norm(query_embedding) * norm(db_embedding))
            else:
                clinic['similarity'] = 0 # Assign low similarity if no embedding
        ranked_clinics = sorted(candidate_clinics, key=lambda x: x.get('similarity', 0), reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION (with comprehensive context)
    context = ""
    if top_5_clinics:
        context += f"I searched using these filters: {filters}.\n"
        context += "Here are the most relevant clinics I found:\n"
        for clinic in top_5_clinics:
            # UPGRADE #1: The Comprehensive Context Line
            context += f"- Name: {clinic.get('name')}, Township: {clinic.get('township')}, Rating: {clinic.get('rating')} stars. Sentiments -> Skill: {clinic.get('sentiment_dentist_skill')}, Pain: {clinic.get('sentiment_pain_management')}, Staff: {clinic.get('sentiment_staff_service')}, Value: {clinic.get('sentiment_cost_value')}, Ambiance: {clinic.get('sentiment_ambiance_cleanliness')}, Convenience: {clinic.get('sentiment_convenience')}.\n"
    else:
        context = "I could not find any clinics that matched your specific criteria, even after broadening my search."

    augmented_prompt = f"""
    You are a helpful assistant. Answer the user's question based ONLY on the context. Summarize the findings in a conversational way.
    IMPORTANT RULE: If the user's question or the context mentions distance, you MUST append this sentence to the VERY END of your response, on a new line:
    "(Please note: all distances are measured from the Johor Bahru CIQ complex.)"
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}