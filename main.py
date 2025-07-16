import os
import re # NEW: Import the regular expression library
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from supabase import create_client, Client

# --- Load environment variables and configure clients ---
load_dotenv()

# Google AI
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# Supabase
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- Pydantic Data Model ---
class UserQuery(BaseModel):
    message: str

# --- FastAPI App ---
app = FastAPI()

# --- A helper function to find townships in the user's message ---
TOWNSHIPS = ["Permas Jaya", "Taman Molek", "Johor Bahru", "Tebrau", "Skudai"]

def find_township_in_message(message):
    for township in TOWNSHIPS:
        if re.search(township, message, re.IGNORECASE):
            return township
    return "" # Return an empty string if no township is found

@app.get("/")
def read_root():
    return {"message": "Hello, the SG-JB Dental Chatbot server is running!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"Received message: '{query.message}'")

    # --- STEP 1: Extract metadata and generate embedding ---
    township_filter = find_township_in_message(query.message)
    print(f"Found township filter: '{township_filter}'")

    query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
    query_embedding = query_embedding_response['embedding']

    # --- STEP 2: Call the NEW Supabase function with the township filter ---
    response = supabase.rpc('match_clinics', {
        'query_embedding': query_embedding,
        'p_township': township_filter,
        'match_count': 5
    }).execute()
    
    # --- STEP 3: Build the context for the AI ---
    context = ""
    if response.data:
        context += "Based on your question, here are the most relevant clinics I found:\n"
        for clinic in response.data:
            clinic_info = f"- Clinic Name: {clinic.get('name', 'N/A')}, Address: {clinic.get('address', 'N/A')}, Rating: {clinic.get('rating', 'N/A')} stars ({clinic.get('reviews', 'N/A')} reviews)."
            
            services = []
            if clinic.get('teeth_whitening'): services.append("Teeth Whitening")
            if clinic.get('dental_implant'): services.append("Dental Implants")
            if clinic.get('dental_crown'): services.append("Dental Crowns")
            
            if services:
                clinic_info += f" Offers: {', '.join(services)}."
            
            context += clinic_info + "\n"
    else:
        context = f"I could not find any clinics in the '{township_filter}' area that matched your question." if township_filter else "I could not find any clinics that matched your question."

    # --- STEP 4: Generate the final answer ---
    augmented_prompt = f"""
    You are a helpful assistant for the SG-JB Dental Platform.
    Your task is to answer the user's question based ONLY on the context provided below.
    Form a helpful, conversational answer. If the context is empty, say so politely.

    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """

    try:
        ai_response = generation_model.generate_content(augmented_prompt)
        return {"response": ai_response.text}
    except Exception as e:
        return {"response": f"An error occurred: {e}"}