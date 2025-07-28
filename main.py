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
class UserQuery(BaseModel): message: str
class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class SearchFilters(BaseModel):
    township: str = Field(None, description="Extract the city, area, or township. Example: 'Permas Jaya'.")
    min_rating: float = Field(None, description="Extract a minimum Google rating if specified by the user.")
    services: List[ServiceEnum] = Field(None, description="Extract a list of specific, specialized dental services if explicitly named by the user from the known list.")
    max_distance: float = Field(None, description="Extract a maximum distance in kilometers (km) if specified.")

# --- FastAPI App ---
app = FastAPI()
@app.get("/")
def read_root(): return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    print(f"\n--- New Request ---\nUser Query: '{query.message}'")

    # STAGE 1: THE "TWO BRAINS" PLANNER
    # Brain #1: The Factual Brain
    filters = {}
    try:
        response = planner_model.generate_content(query.message, tools=[SearchFilters])
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            function_call = response.candidates[0].content.parts[0].function_call
            if function_call:
                args = function_call.args
                filters = {k: v for k, v in args.items() if v is not None}
        print(f"Factual Brain extracted: {filters}")
    except Exception as e:
        print(f"Factual Brain Error: {e}."); filters = {}
        
    # Brain #2: The Semantic Brain
    ranking_priority = []
    try:
        ranking_prompt = f"""
        Analyze the user's query to determine their priorities. Return a JSON list of the most important sentiment columns to rank by, in order of priority.
        The available columns are: "sentiment_dentist_skill", "sentiment_pain_management", "sentiment_cost_value", "sentiment_staff_service", "sentiment_ambiance_cleanliness", "sentiment_convenience".
        For "quality", prioritize "sentiment_dentist_skill". For "convenience" or "easy", prioritize "sentiment_convenience". For "value" or "price", prioritize "sentiment_cost_value".
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
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)
        query_embedding = query_embedding_response['embedding']
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 30}).execute() # Get a larger pool
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from initial semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    # STAGE 3: THE "TIERED RECOMMENDATION" BRAIN
    top_5_clinics = []
    if candidate_clinics:
        # First, apply any hard filters to the semantic list
        filtered_candidates = []
        if filters:
            for clinic in candidate_clinics:
                match = True
                if filters.get('township') and filters.get('township').lower() not in clinic.get('address', '').lower(): match = False
                if filters.get('min_rating') and (clinic.get('rating') is None or clinic.get('rating', 0) < filters.get('min_rating')): match = False
                if filters.get('services'):
                    for service in filters.get('services'):
                        if not clinic.get(service, False): match = False; break
                if match: filtered_candidates.append(clinic)
        else:
            filtered_candidates = candidate_clinics
        
        print(f"Found {len(filtered_candidates)} candidates after applying factual filters.")

        # Now, perform the tiered ranking on the filtered list
        tier1_perfect_matches = []
        tier2_strong_matches = []
        tier3_best_overall = []

        # Use the ranking priority from the Semantic Brain, with defaults
        if not ranking_priority:
            ranking_priority = ['sentiment_dentist_skill', 'sentiment_convenience', 'sentiment_cost_value']
        
        primary_priority = ranking_priority[0]
        secondary_priorities = ranking_priority[1:]

        for clinic in filtered_candidates:
            # Tier 1: Perfect match (has high scores for ALL requested priorities)
            is_perfect_match = True
            for priority in ranking_priority:
                if (clinic.get(priority) or 0) < 8.0: # Threshold for "high score"
                    is_perfect_match = False; break
            if is_perfect_match:
                tier1_perfect_matches.append(clinic)
            # Tier 2: Strong match (has a high score for the MOST important priority)
            elif (clinic.get(primary_priority) or 0) >= 8.0:
                tier2_strong_matches.append(clinic)
            # Tier 3: Good overall clinics
            else:
                tier3_best_overall.append(clinic)
        
        # Sort each tier internally by the full priority list for consistency
        sort_key = lambda x: tuple(x.get(key, 0) or 0 for key in ranking_priority + ['rating', 'reviews'])
        tier1_perfect_matches.sort(key=sort_key, reverse=True)
        tier2_strong_matches.sort(key=sort_key, reverse=True)
        tier3_best_overall.sort(key=lambda x: (x.get('sentiment_overall', 0) or 0, x.get('rating', 0) or 0), reverse=True)

        # Combine the tiers to get our final list
        final_ranked_list = tier1_perfect_matches + tier2_strong_matches + tier3_best_overall
        top_5_clinics = final_ranked_list[:5]

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += "Here are the best matches I found for your request, ranked by how well they fit your priorities:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Location: {clinic.get('address')}, Rating: {clinic.get('rating')} stars. Key Sentiments -> Overall: {clinic.get('sentiment_overall')}, Convenience: {clinic.get('sentiment_convenience')}, Skill: {clinic.get('sentiment_dentist_skill')}, Value: {clinic.get('sentiment_cost_value')}.\n"
    else:
        context = "I'm sorry, I could not find any clinics that matched your search criteria in the database."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your goal is to provide a helpful, data-driven recommendation based ONLY on the context provided.
    Synthesize the data into a conversational answer. Explain WHY the clinics are a good match, referencing their specific sentiment scores.
    **FORMATTING RULE: You MUST use paragraphs. Start with an intro. Present each clinic in its own paragraph with the name in bold. End with a summary.**
    You must correctly interpret NULL/None values, stating 'a specific score was not available'.
    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}