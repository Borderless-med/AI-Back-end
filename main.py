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