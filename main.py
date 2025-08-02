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
ranking_model = genai.Generativeai.GenerativeModel('gemini-1.5-flash-latest') 
embedding_model = 'models/embedding-001'
generation_model = genai.Generativeai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class UserQuery(BaseModel):
    message: str

class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating if specified by the user.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of specific, specialized dental services if explicitly named by the user from the known list.")

# --- FastAPI App ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: THE "TWO BRAINS" PLANNER
    filters = {}
    try:
        response = planner_model.generate_content(query.message, tools=[SearchFilters])
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            function_call = response.candidates[0].content.parts[0].function_call
            if function_call:
                args = function_call.args
                filters = {k: v for k, v in args.items() if v is not None and v != []}
        print(f"Factual Brain extracted: {filters}")
    except Exception as e:
        print(f"Factual Brain Error: {e}."); filters = {}
        
    ranking_priority_dicts = []
    try:
        ranking_prompt = f"""
        You are a senior analyst. Analyze the user's query to identify concepts like skill, cost, convenience, etc.
        Map these concepts to the available database columns: "sentiment_dentist_skill", "sentiment_cost_value", "sentiment_convenience".
        Return a JSON list of objects, where each object has a 'column' key. Example: [{{"column": "sentiment_dentist_skill"}}]
        If the query is too generic, return an empty list.
        USER QUERY: "{query.message}"
        """
        response = ranking_model.generate_content(ranking_prompt)
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        ranking_priority_dicts = json.loads(json_text)
        print(f"Semantic Brain identified priority objects: {ranking_priority_dicts}")
    except Exception as e:
        print(f"Semantic Brain Error: {e}.")
        ranking_priority_dicts = []

    # *** THIS IS THE FIX: Convert list of dictionaries to list of strings ***
    ranking_priority = [item['column'] for item in ranking_priority_dicts if isinstance(item, dict) and 'column' in item]
    print(f"Extracted ranking priority list: {ranking_priority}")


    # STAGE 2: "SEMANTIC-FIRST" SEARCH
    candidate_clinics = []
    print("Performing initial semantic search...")
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY")
        query_embedding = query_embedding_response['embedding']
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 25}).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: REVISED FILTERING AND "OBJECTIVE-FIRST" RANKING
    qualified_clinics = []
    if candidate_clinics:
        # Step 3A: The Quality Gate Filter
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                qualified_clinics.append(clinic)
        print(f"Found {len(qualified_clinics)} candidates after applying Quality Gate (rating >= 4.5, reviews >= 30).")

        # Step 3B: Apply Factual Filters (if any)
        if filters:
            factually_filtered_clinics = []
            for clinic in qualified_clinics:
                match = True
                if filters.get('township') and filters.get('township').lower() not in clinic.get('address', '').lower(): match = False
                if filters.get('min_rating') and (clinic.get('rating') is None or clinic.get('rating', 0) < filters.get('min_rating')): match = False
                if filters.get('services'):
                    for service in filters.get('services'):
                        if not clinic.get(service, False): match = False; break
                if match: factually_filtered_clinics.append(clinic)
            qualified_clinics = factually_filtered_clinics
            print(f"Found {len(qualified_clinics)} candidates after applying factual filters.")

    top_clinics = []
    if qualified_clinics:
        # Step 3C: THE "OBJECTIVE-FIRST" RANKING LOGIC
        objective_keys = ['rating', 'reviews']
        final_ranking_keys = objective_keys + ranking_priority
        final_ranking_keys = list(dict.fromkeys(final_ranking_keys))
        
        print(f"Using OBJECTIVE-FIRST ranking with priorities: {final_ranking_keys}")
        
        ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in final_ranking_keys), reverse=True)
        top_clinics = ranked_clinics[:5]

    # STAGE 4: FINAL RESPONSE GENERATION WITH ENHANCED FORMATTING
    context = ""
    if top_clinics:
        clinic_data_for_prompt = []
        for clinic in top_clinics:
            clinic_info = {
                "name": clinic.get('name'), "address": clinic.get('address'), "distance": clinic.get('distance'),
                "rating": clinic.get('rating'), "reviews": clinic.get('reviews'),
                "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),
            }
            clinic_data_for_prompt.append(clinic_info)
        context = json.dumps(clinic_data_for_prompt, indent=2) 
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria after applying our quality standards."

    augmented_prompt = f"""
    You are an expert, friendly, and highly readable dental clinic assistant for Johor Bahru. Your goal is to provide a rich, data-driven recommendation based ONLY on the JSON context provided. You must emulate the exact style of the "Gold Standard" example.

    **USER'S ORIGINAL QUESTION:**
    {query.message}

    **CONTEXT (TOP CLINICS FOUND IN JSON FORMAT):**
    ```json
    {context}
    ```

    **YOUR TASK:**
    Synthesize the provided JSON data into a helpful, structured recommendation. You MUST follow these rules precisely:

    1.  **Opening:** Start with a friendly, professional introductory sentence that acknowledges the user's needs.
    2.  **Categorization:** Structure the recommendations using these categories and emojis: 🏆 Top Choice, 🌟 Excellent Alternatives. Use the "Excellent Alternatives" heading only once for the subsequent high-quality clinics.
    3.  **Formatting for EACH Clinic:**
        - Start with the emoji and category title (e.g., "🏆 Top Choice:").
        - On the next line, list the clinic **name in bold**.
        - On new lines below that, list: Rating (with a ★ symbol and review count), Address, Hours, and Website (if available).
        - Include a "Why it's great:" line where you BRIEFLY synthesize WHY it's a good match.
        - **CRITICAL: You MUST add a blank line between each full clinic recommendation to ensure readability.**
    4.  **Final Summary:** After listing the clinics, you MUST include a conclusive "💡 My Recommendation:" summary paragraph. In this paragraph, synthesize your findings and give a final, definitive recommendation to the user.
    5.  **Closing:** End the entire response by asking an engaging follow-up question, like "Would you like me to provide more specific information about pricing or help you with booking details for any of these clinics?"
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}```

4.  **Save the file.**

This corrected version properly handles the new data structure from the AI and should resolve the 500 error. Please commit and push this version to Render.