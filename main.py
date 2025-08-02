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
        
    ranking_priority = []
    try:
        ranking_prompt = f"""
        You are a senior analyst specializing in customer intent. Your task is to analyze a user's query about finding a dental clinic and determine their ranked priorities.
        1. Read the user's query carefully. Identify the key concepts they care about (e.g., skill, cost, pain, speed, service, etc.).
        2. Map these concepts to the available database columns: "sentiment_dentist_skill", "sentiment_pain_management", "sentiment_cost_value", "sentiment_staff_service", "sentiment_ambiance_cleanliness", "sentiment_convenience".
        3. Crucially, determine the order of importance based on the user's language. For example, if a user says "I need a really high quality dentist, and convenience is also nice," 'quality' (`sentiment_dentist_skill`) is clearly the top priority, and 'convenience' is secondary.
        4. Return a JSON list of these database columns in descending order of importance. If the query is too generic to determine a clear priority, return an empty list.
        USER QUERY: "{query.message}"
        """
        response = ranking_model.generate_content(ranking_prompt)
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        ranking_priority = json.loads(json_text)
        print(f"Semantic Brain determined ranking priority: {ranking_priority}")
    except Exception as e:
        print(f"Semantic Brain Error: {e}.")
        ranking_priority = []

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

    # STAGE 3: THE NEW, ROBUST FILTERING AND RANKING LOGIC
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

    top_5_clinics = []
    if qualified_clinics:
        # Step 3C: The Ranking Logic
        if ranking_priority:
            # User has specific priorities: Use ranked-order sort
            print(f"Using user-specific ranking: {ranking_priority}")
            final_ranking_keys = ranking_priority + ['rating', 'reviews']
            final_ranking_keys = list(dict.fromkeys(final_ranking_keys)) # Remove duplicates
            
            ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in final_ranking_keys), reverse=True)
            top_5_clinics = ranked_clinics[:5]

        else:
            # User query was generic: Use a default weighted score
            print("Generic query detected. Applying default weighted ranking.")
            # Normalize review count for fair weighting (logarithmic scale is good for this)
            max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
            
            for clinic in qualified_clinics:
                norm_rating = (clinic.get('rating', 0) - 1) / 4.0 # Normalizes 1-5 scale to 0-1
                norm_sentiment = clinic.get('sentiment_overall', 0) / 10.0 # Normalizes 0-10 scale to 0-1
                norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews) # Log-normalized
                
                # Weighted score: 50% rating, 30% overall sentiment, 20% review count
                clinic['weighted_score'] = (norm_rating * 0.5) + (norm_sentiment * 0.3) + (norm_reviews * 0.2)
            
            ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('weighted_score', 0), reverse=True)
            top_5_clinics = ranked_clinics[:5]

    # STAGE 4: FINAL RESPONSE GENERATION WITH "GOLD STANDARD" FORMATTING
    context = ""
    if top_5_clinics:
        # Create a detailed JSON string for the AI to parse easily.
        clinic_data_for_prompt = []
        for clinic in top_5_clinics:
            clinic_info = {
                "name": clinic.get('name'), "address": clinic.get('address'),
                "rating": clinic.get('rating'), "reviews": clinic.get('reviews'),
                "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),
                "sentiments": {
                    "skill": clinic.get('sentiment_dentist_skill'),
                    "convenience": clinic.get('sentiment_convenience'),
                    "value": clinic.get('sentiment_cost_value')
                }
            }
            clinic_data_for_prompt.append(clinic_info)
        context = json.dumps(clinic_data_for_prompt, indent=2) 
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria after applying our quality standards."

    augmented_prompt = f"""
    You are an expert, friendly, and helpful dental clinic assistant for Johor Bahru. Your goal is to provide a rich, data-driven, and highly readable recommendation based ONLY on the JSON context provided. You must emulate the exact style and structure of the "Gold Standard" example.

    **USER'S ORIGINAL QUESTION:**
    {query.message}

    **CONTEXT (TOP CLINICS FOUND IN JSON FORMAT):**
    ```json
    {context}
    ```

    **YOUR TASK:**
    Synthesize the provided JSON data into a helpful, structured recommendation. You MUST follow these rules precisely:
    1.  Start with a clear introductory sentence that acknowledges the user's core needs.
    2.  Structure the recommendations using these categories and emojis: 🏆 Top Choice, 🥈 Excellent Alternative, and 🌟 Strong Contender. Use each category at least once if there are enough clinics.
    3.  For EACH clinic, you MUST format it as follows:
        - Start with the emoji, category title, and the clinic name in bold.
        - On new lines, list: Rating (with a ★ symbol and review count in parentheses), Address, and Operating Hours. If a website_url exists, list that too.
        - Include a "Why it's a great match:" line where you BRIEFLY synthesize WHY it's a good fit for the user's needs, using the data (e.g., "Perfect rating and high convenience score make it a top choice.").
    4.  After the list of clinics, you MUST include a "💡 Pro Tips:" section with at least three pieces of general advice for booking dental appointments.
    5.  End your entire response by asking an engaging follow-up question.
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}