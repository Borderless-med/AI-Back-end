import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional
import json

# --- Load environment variables and configure clients ---
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- AI Model ---
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models ---
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

    # STAGE 1: SIMPLE DATABASE FETCH
    try:
        db_response = supabase.table("clinics_data").select("*").gte("rating", 4.5).gte("reviews", 30).execute()
        all_clinics = db_response.data if db_response.data else []
        print(f"Fetched {len(all_clinics)} high-quality clinics from the database.")
    except Exception as e:
        print(f"Database fetch error: {e}")
        return {"response": "I'm sorry, I'm having trouble connecting to the clinic database right now."}

    # STAGE 2: AI-POWERED REFINEMENT AND FILTERING
    filtered_clinics = []
    try:
        # We need the IDs for the final step of the prompt
        all_clinic_ids = [c['id'] for c in all_clinics]

        refiner_prompt = f"""
        You are a strict data filtering engine. Your only job is to take a user's query and a list of clinics, and return a new list containing ONLY the clinics that meet the user's hard constraints.

        **USER'S QUERY:**
        "{query.message}"

        **LIST OF CLINICS TO FILTER (in JSON format):**
        {json.dumps(all_clinics, indent=2)}

        **YOUR TASK:**
        1.  Identify all specific, non-negotiable constraints from the user's query (e.g., locations, services).
        2.  **If the query is general and has no hard constraints (e.g., "best clinics"), your task is to return a JSON list containing the IDs of ALL the clinics provided in the context.**
        3.  If the query has constraints, carefully check each clinic and keep ONLY the ones that meet ALL constraints.
        4.  Your final output MUST be ONLY a valid JSON list of the matching clinic IDs, like `[12, 45, 98]`. If no clinics match, return an empty list `[]`.
        """
        
        refiner_response = generation_model.generate_content(refiner_prompt)
        json_text = refiner_response.text.strip().replace("```json", "").replace("```", "")
        matching_ids = json.loads(json_text)
        
        id_map = {clinic['id']: clinic for clinic in all_clinics}
        filtered_clinics = [id_map[id] for id in matching_ids if id in id_map]
        print(f"Refiner Brain returned {len(filtered_clinics)} matching clinics.")
    except Exception as e:
        print(f"Refiner Brain Error: {e}. Falling back to the full list.")
        filtered_clinics = all_clinics

    # STAGE 3: FINAL RANKING
    top_clinics = []
    if filtered_clinics:
        ranked_clinics = sorted(filtered_clinics, key=lambda x: (x.get('rating', 0), x.get('reviews', 0)), reverse=True)
        top_clinics = ranked_clinics[:3]
        print(f"Ranking complete. Top clinic: {top_clinics[0]['name'] if top_clinics else 'N/A'}")

    # STAGE 4: FINAL RESPONSE GENERATION
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
        context = "I'm sorry, I could not find any clinics that matched your specific search criteria."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your task is to generate a concise, data-driven recommendation based on the provided JSON context. Your response must be friendly, professional, and perfectly formatted.
    **CONTEXT (TOP CLINICS FOUND):**
    ```json
    {context}
    ```
    **--- EXAMPLE OF PERFECT RESPONSE ---**
    Based on your criteria, here are my top recommendations:
    🏆 **Top Choice: JDT Dental**
    *   **Rating:** 4.9★ (1542 reviews)
    *   **Address:** 41B, Jalan Kuning 2, Taman Pelangi, Johor Bahru
    *   **Hours:** Daily: 9:00 AM – 6:00 PM
    *   **Why it's great:** An exceptionally high rating combined with a massive number of reviews indicates consistently excellent service.
    ---
    **MANDATORY RULES:**
    1.  Emulate the tone and structure of the example.
    2.  Use bullet points (`* `) for details.
    3.  Add a blank line between each clinic block.
    4.  Summarize operating hours concisely.
    5.  Keep the "Why it's great" and "My Recommendation" sections brief.
    """
    
    final_response = generation_model.generate_content(augmented_prompt)

    return {"response": final_response.text}