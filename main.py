import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
import numpy as np
from numpy.linalg import norm
import json

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
    max_distance: float = Field(None, description="The maximum acceptable distance in kilometers from a reference point (like the CIQ). E.g., for 'within 10km', this would be 10.")

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
        response = planner_model.generate_content(f"Extract search filters from this query: '{query.message}'", tools=[SearchFilters])
        if response.candidates and response.candidates[0].content.parts and response.candidates[0].content.parts[0].function_call:
            function_call = response.candidates[0].content.parts[0].function_call
            args = function_call.args
            service_value = args.get("service")
            filters = {"township": args.get("township"), "min_rating": args.get("min_rating"), "service": service_value.value if isinstance(service_value, Enum) else service_value, "max_distance": args.get("max_distance")}
        else:
            print("AI Planner did not return any structured filters.")
    except Exception as e:
        print(f"AI Planner Error: {e}.")
    
    print(f"AI-extracted filters: {filters}")

    # STAGE 2: FACTUAL FILTERING
    query_builder = supabase.table('clinics_data').select('id, name, address, township, rating, reviews, embedding, distance')
    if filters.get('township'): query_builder = query_builder.ilike('township', f"%{filters['township']}%")
    if filters.get('min_rating'): query_builder = query_builder.gte('rating', filters['min_rating'])
    
    # <<< THIS IS THE CORRECTED AND VERIFIED LOGIC >>>
    if filters.get('service'):
        query_builder = query_builder.eq(filters.get('service'), True)
        
    if filters.get('max_distance'): query_builder = query_builder.lte('distance', filters['max_distance'])
    
    db_response = query_builder.execute()
    candidate_clinics = db_response.data if db_response.data else []
    print(f"Found {len(candidate_clinics)} candidates after factual filtering.")

    # STAGES 3 & 4 remain the same...
    if candidate_clinics:
        query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")['embedding']
        for clinic in candidate_clinics:
            db_embedding = json.loads(clinic['embedding'])
            clinic['similarity'] = np.dot(query_embedding, db_embedding) / (norm(query_embedding) * norm(db_embedding))
        ranked_clinics = sorted(candidate_clinics, key=lambda x: x['similarity'], reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    context = ""
    if top_5_clinics:
        context += "Based on my search, here are the most relevant clinics I found:\n"
        for clinic in top_5_clinics:
            clinic_info = f"- Name: {clinic.get('name')}, Township: {clinic.get('township')}, Rating: {clinic.get('rating')} stars."
            if clinic.get('distance') is not None: clinic_info += f" Distance: {clinic.get('distance')}km."
            context += clinic_info + "\n"
    else:
        context = "I could not find any clinics that matched your specific criteria in the database."

    augmented_prompt = f"You are a helpful assistant. Answer the user's question based ONLY on the context below. Summarize the findings in a conversational way.\n\nIMPORTANT RULE: After your main answer, if the context below contains the word 'Distance', you MUST add the following sentence at the very end of your response, on a new line:\n\"(Note: All distances are measured from the Johor Bahru CIQ complex.)\"\nDo not add this note if the context does not mention distance.\n\nCONTEXT:\n{context}\n\nUSER'S QUESTION:\n{query.message}"
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}