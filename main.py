import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
from typing import List, Optional
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
# We now only need one model for generation, one for embedding
embedding_model = 'models/embedding-001'
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

    # STAGE 1: ALWAYS START WITH A BROAD SEMANTIC SEARCH
    candidate_clinics = []
    print("Performing initial semantic search to gather context...")
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
        query_embedding = query_embedding_response['embedding']
        # We cast a wide net to ensure all potential candidates are included
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 75}).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 2: THE "REFINER BRAIN" APPLIES HARD FILTERS
    filtered_clinics = []
    if candidate_clinics:
        print("Applying Quality Gate and sending to Refiner Brain...")
        # Step 2A: Apply the non-negotiable Quality Gate first
        quality_gated_clinics = []
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                quality_gated_clinics.append(clinic)
        print(f"Found {len(quality_gated_clinics)} candidates after Quality Gate.")
        
        # Step 2B: The Refiner Brain filters the high-quality list
        try:
            context_for_refiner = []
            for clinic in quality_gated_clinics:
                context_for_refiner.append({
                    "id": clinic.get("id"),
                    "name": clinic.get("name"),
                    "address": clinic.get("address"),
                    "services": [k for k, v in clinic.items() if isinstance(v, bool) and v]
                })

            refiner_prompt = f"""
            You are a strict data filtering engine. Your only job is to take a user's query and a list of clinics, and return a new list containing ONLY the clinics that meet the user's hard constraints.

            **USER'S QUERY:**
            "{query.message}"

            **LIST OF CLINICS TO FILTER (in JSON format):**
            {json.dumps(context_for_refiner, indent=2)}

            **YOUR TASK:**
            1.  Identify all specific, non-negotiable constraints from the user's query. These are typically locations (e.g., "Permas Jaya") or specific dental services (e.g., "braces", "implants").
            2.  Carefully check each clinic in the provided list. A clinic is a match ONLY if it meets ALL of the user's constraints. Location matching should be case-insensitive. Service matching requires the exact service name to be in the clinic's "services" list.
            3.  Your final output MUST be ONLY a valid JSON list of the matching clinic IDs, like `[12, 45, 98]`. Do not include any other text or explanation. If no clinics match, return an empty list `[]`.
            """
            
            refiner_response = generation_model.generate_content(refiner_prompt)
            json_text = refiner_response.text.strip().replace("```json", "").replace("```", "")
            matching_ids = json.loads(json_text)
            
            id_map = {clinic['id']: clinic for clinic in quality_gated_clinics}
            filtered_clinics = [id_map[id] for id in matching_ids if id in id_map]
            print(f"Refiner Brain returned {len(filtered_clinics)} matching clinics.")

        except Exception as e:
            print(f"Refiner Brain Error: {e}. Falling back to the quality-gated list.")
            filtered_clinics = quality_gated_clinics
    
    # STAGE 3: FINAL RANKING
    top_clinics = []
    if filtered_clinics:
        print("Calculating weighted quality scores for the final list...")
        max_reviews = max([c.get('reviews', 1) for c in filtered_clinics]) or 1
        
        for clinic in filtered_clinics:
            norm_rating = (clinic.get('rating', 0) - 1) / 4.0
            norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
            clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
        
        ranked_clinics = sorted(filtered_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
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
        # *** THIS IS THE CORRECTED LINE ***
        context = "I'm sorry, I could not find any clinics that matched your specific search criteria after applying our quality standards."

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