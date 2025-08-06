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
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel):
    message: str

# --- FastAPI App ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 2: SEMANTIC SEARCH
    candidate_clinics = []
    print("Performing initial semantic search with a wider net...")
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
        query_embedding = query_embedding_response['embedding']
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 75}).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: FILTERING AND RANKING
    qualified_clinics = []
    if candidate_clinics:
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                qualified_clinics.append(clinic)
        print(f"Found {len(qualified_clinics)} candidates after applying Quality Gate (rating >= 4.5, reviews >= 30).")

    top_clinics = []
    if qualified_clinics:
        print("Calculating weighted quality scores...")
        max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
        
        for clinic in qualified_clinics:
            norm_rating = (clinic.get('rating', 0) - 1) / 4.0
            norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
            clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
        
        ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
        top_clinics = ranked_clinics[:3]
        print(f"Ranking complete. Top clinic by weighted score: {top_clinics[0]['name'] if top_clinics else 'N/A'}")


    # STAGE 4: FINAL RESPONSE GENERATION WITH THE "PERFECT EXAMPLE" PROMPT
    context = ""
    if top_clinics:
        clinic_data_for_prompt = []
        for clinic in top_clinics:
            clinic_info = {
                "name": clinic.get('name'), "address": clinic.get('address'),
                "rating": clinic.get('rating'), "reviews": clinic.get('reviews'),
                "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),
            }
            clinic_data_for_prompt.append(clinic_info)
        context = json.dumps(clinic_data_for_prompt, indent=2)
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria after applying our quality standards."

    # This is the final, definitive prompt. It relies on a high-quality example.
    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your task is to generate a concise, data-driven recommendation.
    Your response must be friendly, professional, and perfectly formatted like the example provided.

    **CONTEXT (TOP CLINICS FOUND):**
    ```json
    {context}
    ```

    **--- YOUR TASK & STRICT RULES ---**

    Synthesize the provided JSON data into a short and highly readable recommendation.
    You MUST exactly emulate the formatting, spacing, tone, and conciseness of the example below.

    **--- EXAMPLE OF PERFECT RESPONSE ---**

    Based on your criteria, here are my top recommendations:

    🏆 **Top Choice: JDT Dental**
    *   **Rating:** 4.9★ (1542 reviews)
    *   **Address:** 41B, Jalan Kuning 2, Taman Pelangi, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** An exceptionally high rating combined with a massive number of reviews indicates consistently excellent service.

    🌟 **Excellent Alternatives:**

    **Austin Dental Group (Mount Austin)**
    *   **Rating:** 4.9★ (1085 reviews)
    *   **Address:** 33G, Jalan Mutiara Emas 10/19, Taman Mount Austin, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** Another highly-rated option with a very strong track record and convenient daily hours.

    **Adda Heights Dental Studio**
    *   **Rating:** 4.9★ (1065 reviews)
    *   **Address:** Ground Floor, 108&110, Jalan Adda 7, Adda Heights, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** A strong combination of high ratings and numerous positive reviews.

    💡 **My Recommendation:**
    Given the exceptionally high volume of positive reviews, JDT Dental is the recommended choice. However, the other two clinics are excellent alternatives depending on your location preference.

    Would you like help with booking an appointment?
    ---
    
    **MANDATORY RULES CHECKLIST:**
    1.  Did you match the tone and structure of the example?
    2.  Did you use bullet points (`* `) for the details under each clinic?
    3.  **Did you add a blank line (two newlines) between each full clinic recommendation block?**
    4.  Did you summarize the operating hours concisely?
    5.  Did you keep the "Why it's great" and "My Recommendation" sections brief and to the point?
    """
    
    final_response = generation_model.generate_content(augmented_prompt)

    return {"response": final_response.text}