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

# --- Pydantic Data Models & Enum (with Upgraded Instructions) ---
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

    # STAGE 1: AI QUERY PLANNER (with new simple, direct prompt)
    filters = {}
    try:
        # The prompt is now simple, the instructions are in the tool definition
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
                    "min_staff_service": args.get("min_staff_service"), "min_ambiance_cleanliness": args.get("min_ambiance_cleanliness"),
                    "min_convenience": args.get("min_convenience")
                }
        print(f"AI-extracted filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}
    
    # STAGE 2: FACTUAL FILTERING
    query_builder = supabase.table('clinics_data').select('*') # Select all columns for rich context
    
    # Create a list of all clinics found by the initial filters
    candidate_clinics = []
    # We build the query dynamically
    if filters:
        # Clean filters to only include those with actual values
        active_filters = {k: v for k, v in filters.items() if v is not None}
        
        if active_filters:
            if active_filters.get('township'):
                query_builder = query_builder.ilike('township', f"%{active_filters['township']}%")
            if active_filters.get('min_rating'):
                query_builder = query_builder.gte('rating', active_filters['min_rating'])
            if active_filters.get('service'):
                query_builder = query_builder.eq(active_filters['service'], True)
            if active_filters.get('max_distance'):
                query_builder = query_builder.lte('distance', active_filters['max_distance'])
            if active_filters.get('min_dentist_skill'):
                query_builder = query_builder.gte('sentiment_dentist_skill', active_filters['min_dentist_skill'])
            if active_filters.get('min_pain_management'):
                query_builder = query_builder.gte('sentiment_pain_management', active_filters['min_pain_management'])
            if active_filters.get('min_cost_value'):
                query_builder = query_builder.gte('sentiment_cost_value', active_filters['min_cost_value'])
            if active_filters.get('min_staff_service'):
                query_builder = query_builder.gte('sentiment_staff_service', active_filters['min_staff_service'])
            if active_filters.get('min_ambiance_cleanliness'):
                query_builder = query_builder.gte('sentiment_ambiance_cleanliness', active_filters['min_ambiance_cleanliness'])
            if active_filters.get('min_convenience'):
                query_builder = query_builder.gte('sentiment_convenience', active_filters['min_convenience'])
    
    db_response = query_builder.execute()
    candidate_clinics = db_response.data if db_response.data else []
    print(f"Found {len(candidate_clinics)} candidates after factual filtering.")

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
    # If no candidates from filtering, do a pure semantic search as a final fallback
    elif not filters:
         print("No filters extracted. Performing pure semantic search as fallback.")
         query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")['embedding']
         # Call a database function for vector search
         db_response = supabase.rpc('match_clinics_semantic_only', {'query_embedding': query_embedding, 'match_count': 5}).execute()
         top_5_clinics = db_response.data if db_response.data else []
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += f"I searched using these filters: {filters}.\n"
        context += "Here are the most relevant clinics I found:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Township: {clinic.get('township')}, Rating: {clinic.get('rating')} stars. Sentiments -> Skill: {clinic.get('sentiment_dentist_skill')}, Pain: {clinic.get('sentiment_pain_management')}, Staff: {clinic.get('sentiment_staff_service')}, Value: {clinic.get('sentiment_cost_value')}, Ambiance: {clinic.get('sentiment_ambiance_cleanliness')}, Convenience: {clinic.get('sentiment_convenience')}.\n"
    else:
        context = "I could not find any clinics that matched your specific criteria in the database."

    augmented_prompt = f"""
    You are a helpful assistant. Answer the user's question based ONLY on the context. Summarize the findings in a conversational way.
    IMPORTANT RULE: If the user's question or the context provided mentions distance, you MUST append the following sentence to the VERY END of your response, on a new line:
    "(Please note: all distances are measured from the Johor Bahru CIQ complex.)"
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}