<<<<<<< HEAD
import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from scipy.spatial.distance import cosine
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
    try:
        response = planner_model.generate_content(f"Extract search filters from this query: '{query.message}'", tools=[SearchFilters])
        function_call = response.candidates[0].content.parts[0].function_call
        args = function_call.args
        service_value = args.get("service")
        filters = {
            "township": args.get("township"), 
            "min_rating": args.get("min_rating"), 
            "service": service_value.value if isinstance(service_value, Enum) else service_value,
            "max_distance": args.get("max_distance")
        }
        print(f"AI-extracted filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}

    # STAGE 2: FACTUAL FILTERING
    query_builder = supabase.table('clinics_data').select('id, name, address, township, rating, reviews, embedding, distance')
    
    if filters.get('township'): query_builder = query_builder.ilike('township', f"%{filters['township']}%")
    if filters.get('min_rating'): query_builder = query_builder.gte('rating', filters['min_rating'])
    if filters.get('service'): query_builder = query_builder.eq(filters['service'], True)
    if filters.get('max_distance'): query_builder = query_builder.lte('distance', filters['max_distance'])
    
    db_response = query_builder.execute()
    candidate_clinics = db_response.data if db_response.data else []
    print(f"Found {len(candidate_clinics)} candidates after factual filtering.")

    # STAGE 3: SEMANTIC RANKING
    if candidate_clinics:
        query_embedding = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")['embedding']
        
        for clinic in candidate_clinics:
            db_embedding = json.loads(clinic['embedding'])
            clinic['similarity'] = 1 - cosine(query_embedding, db_embedding)

        ranked_clinics = sorted(candidate_clinics, key=lambda x: x['similarity'], reverse=True)
        top_5_clinics = ranked_clinics[:5]
    else:
        top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += f"I searched for clinics with the following criteria: {filters}.\n"
        context += "Based on your request, here are the most relevant clinics I found:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Township: {clinic.get('township')}, Rating: {clinic.get('rating')} stars, Distance: {clinic.get('distance')}km.\n"
    else:
        context = "I could not find any clinics that matched your specific criteria in the database."

    # <<< THIS IS THE CRITICAL FIX: THE PREFACE INSTRUCTION >>>
    augmented_prompt = f"""
    You are a helpful assistant for the SG-JB Dental Platform.
    Your task is to provide a conversational answer to the user's question based ONLY on the context provided.
    
    IMPORTANT RULE: If your answer mentions distance or lists clinics with distances, you MUST preface your entire response with the sentence: "Please note, all distances are measured from the Johor Bahru CIQ complex."

    Assume the context is 100% correct. Do not apologize or say you cannot access information.
    Summarize the findings in a helpful, confident way.

    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}
=======
import os
import re
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- Pydantic Data Model ---
class UserQuery(BaseModel):
    message: str

# --- FastAPI App with CORS ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# --- The COMPLETE list of known townships ---
TOWNSHIPS = [
    "Adda Heights", "Bandar Baru Uda", "Bandar Dato Onn", "Bandar Putra", "Bandar Putra Kulai",
    "Batu Pahat", "Bukit Indah", "City Centre", "Eco Botanic", "Gelang Patah", "Horizon Hills",
    "Impian Emas", "Johor Jaya", "Kota Masai", "Kulai", "Larkin", "Masai", "Mount Austin",
    "Mutiara Rini", "Pekan Nanas", "Permas Jaya", "Pontian", "Setia Tropika", "Skudai",
    "Southkey", "Taman Abad", "Taman Century", "Taman Daya", "Taman Desa Tebrau", "Taman Johor Jaya",
    "Taman Kebun Teh", "Taman Molek", "Taman Mutiara Mas", "Taman Nusa Bestari", "Taman Pelangi",
    "Taman Perling", "Taman Pulai Mutiara", "Taman Rinting", "Taman Scientex", "Taman Sentosa",
    "Taman Sri Tebrau", "Taman Sutera Utama", "Taman Ungku Tun Aminah", "Taman Universiti",
    "Tampoi", "Tebrau", "Ulu Tiram"
]

def find_township_in_message(message):
    for township in TOWNSHIPS:
        # Using word boundaries (\b) for more accurate matching
        if re.search(r'\b' + re.escape(township) + r'\b', message, re.IGNORECASE):
            return township
    return ""

@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    user_message = query.message
    print(f"Received message: '{user_message}'")
    township_filter = find_township_in_message(user_message)
    print(f"Found township filter: '{township_filter}'")

    query_embedding_response = genai.embed_content(model=embedding_model, content=user_message, task_type="RETRIEVAL_QUERY")
    query_embedding = query_embedding_response['embedding']

    response = supabase.rpc('match_clinics', {'query_embedding': query_embedding, 'p_township': township_filter, 'match_count': 5}).execute()
    
    context = ""
    if response.data:
        context += "Based on your question, here are the most relevant clinics I found:\n"
        for clinic in response.data:
            clinic_info = f"- Clinic Name: {clinic.get('name', 'N/A')}, Address: {clinic.get('address', 'N/A')}, Rating: {clinic.get('rating', 'N/A')} stars ({clinic.get('reviews', 'N/A')} reviews)."
            
            # --- The COMPLETE list of services logic ---
            services = []
            if clinic.get('tooth_filling'): services.append("Tooth Filling")
            if clinic.get('root_canal'): services.append("Root Canal")
            if clinic.get('dental_crown'): services.append("Dental Crown")
            if clinic.get('dental_implant'): services.append("Dental Implant")
            if clinic.get('teeth_whitening'): services.append("Teeth Whitening")
            if clinic.get('braces'): services.append("Braces")
            if clinic.get('wisdom_tooth'): services.append("Wisdom Tooth Removal")
            if clinic.get('gum_treatment'): services.append("Gum Treatment")
            if clinic.get('composite_veneers'): services.append("Composite Veneers")
            if clinic.get('porcelain_veneers'): services.append("Porcelain Veneers")
            if clinic.get('dental_bonding'): services.append("Dental Bonding")
            if clinic.get('inlays_onlays'): services.append("Inlays/Onlays")
            if clinic.get('enamel_shaping'): services.append("Enamel Shaping")
            if clinic.get('gingivectomy'): services.append("Gingivectomy")
            if clinic.get('bone_grafting'): services.append("Bone Grafting")
            if clinic.get('sinus_lift'): services.append("Sinus Lift")
            if clinic.get('frenectomy'): services.append("Frenectomy")
            if clinic.get('tmj_treatment'): services.append("TMJ Treatment")
            if clinic.get('sleep_apnea_appliances'): services.append("Sleep Apnea Appliances")
            if clinic.get('crown_lengthening'): services.append("Crown Lengthening")
            if clinic.get('oral_cancer_screening'): services.append("Oral Cancer Screening")
            if clinic.get('alveoplasty'): services.append("Alveoplasty")

            if services:
                clinic_info += f" Offers: {', '.join(services)}."
            
            context += clinic_info + "\n"
    else:
        context = f"I could not find any clinics in the '{township_filter}' area that matched your question." if township_filter else "I could not find any clinics that matched your question."

    augmented_prompt = f"""
    You are a helpful assistant for the SG-JB Dental Platform. Answer the user's question based ONLY on the context provided.
    If the context is empty, say so politely.

    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {user_message}
    """

    try:
        ai_response = generation_model.generate_content(augmented_prompt)
        return {"response": ai_response.text}
    except Exception as e:
        return {"response": f"An error occurred: {e}"}
>>>>>>> a819859ff75dbd3af7bae560d4ad49599e0b3a6b
