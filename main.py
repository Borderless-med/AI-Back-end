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
factual_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
ranking_brain_model = genai.GenerativeModel('gemini-1.5-flash-latest')
query_planner_model = genai.GenerativeModel('gemini-1.5-flash-latest')
embedding_model = 'models/embedding-001'
generation_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Pydantic Data Models & Enum ---
class ChatMessage(BaseModel):
    role: str
    content: str

class UserQuery(BaseModel):
    history: List[ChatMessage]
    applied_filters: Optional[dict] = Field(None, description="The filters that were successfully applied in the previous turn.")

class ServiceEnum(str, Enum):
    tooth_filling = 'tooth_filling'; root_canal = 'root_canal'; dental_crown = 'dental_crown'; dental_implant = 'dental_implant'; wisdom_tooth = 'wisdom_tooth'; gum_treatment = 'gum_treatment'; dental_bonding = 'dental_bonding'; inlays_onlays = 'inlays_onlays'; teeth_whitening = 'teeth_whitening'; composite_veneers = 'composite_veneers'; porcelain_veneers = 'porcelain_veneers'; enamel_shaping = 'enamel_shaping'; braces = 'braces'; gingivectomy = 'gingivectomy'; bone_grafting = 'bone_grafting'; sinus_lift = 'sinus_lift'; frenectomy = 'frenectomy'; tmj_treatment = 'tmj_treatment'; sleep_apnea_appliances = 'sleep_apnea_appliances'; crown_lengthening = 'crown_lengthening'; oral_cancer_screening = 'oral_cancer_screening'; alveoplasty = 'alveoplasty'

class UserIntent(BaseModel):
    service: Optional[ServiceEnum] = Field(None, description="Extract any specific dental service mentioned.")
    township: Optional[str] = Field(None, description="Extract any specific location or township mentioned.")

class FilterAction(str, Enum):
    MERGE = "MERGE"
    REPLACE = "REPLACE"

class QueryPlan(BaseModel):
    action: FilterAction = Field(..., description="Decide whether to MERGE new filters with old ones or REPLACE them.")
    reason: str = Field(..., description="A brief explanation for the decision (e.g., 'User is refining their search' or 'User is changing the topic').")

# --- FastAPI App ---
app = FastAPI()

RESET_KEYWORDS = ["never mind", "start over", "reset", "forget that", "actually"]

@app.get("/")
def read_root():
    return {"message": "Hello!"}

@app.post("/chat")
def handle_chat(query: UserQuery):
    if not query.history:
        return {"response": "Error: History is empty."}
    
    latest_user_message = query.history[-1].content.lower()
    previous_filters = query.applied_filters or {}
    
    conversation_history_for_prompt = ""
    for msg in query.history[:-1]:
        conversation_history_for_prompt += f"{msg.role}: {msg.content}\n"

    print(f"\n--- New Request ---")
    print(f"Latest User Query: '{latest_user_message}'")
    print(f"Previous Filters: {previous_filters}")

    current_filters = {}
    try:
        prompt_text = f"Extract entities from this query: '{latest_user_message}'"
        factual_response = factual_brain_model.generate_content(prompt_text, tools=[UserIntent])
        function_call = factual_response.candidates[0].content.parts[0].function_call
        if function_call and function_call.args:
            args = function_call.args
            if args.get('service'): current_filters['services'] = [args.get('service')]
            if args.get('township'): current_filters['township'] = args.get('township')
        print(f"Factual Brain extracted: {current_filters}")
    except (IndexError, AttributeError, Exception) as e:
        print(f"Factual Brain Error: {e}")
        current_filters = {}

    final_filters = previous_filters.copy()
    user_wants_to_reset = any(keyword in latest_user_message for keyword in RESET_KEYWORDS)

    if current_filters or (user_wants_to_reset and previous_filters):
        try:
            planner_prompt = f"""
            Your job is to decide if a user wants to MERGE filters or REPLACE them.
            
            **Rules:**
            - REPLACE if the user signals a topic change. Keywords like "never mind", "start over", "actually", or asking for a completely different service (e.g., previous was 'braces', new is 'whitening') mean REPLACE.
            - MERGE if the user is refining their current search. Keywords like "what about", "in", "which of those" or adding a location to a service mean MERGE.

            **Analysis:**
            - Previous Filters: {json.dumps(previous_filters)}
            - Latest User Query: "{latest_user_message}"
            - New Entities Found: {json.dumps(current_filters)}

            Does this query indicate a topic change (REPLACE) or a refinement (MERGE)?
            """
            planner_response = query_planner_model.generate_content(planner_prompt, tools=[QueryPlan])
            
            # THE FIX: Add defensive checks to ensure the AI response is valid before using it.
            plan_tool_call = planner_response.candidates[0].content.parts[0].function_call
            
            if plan_tool_call and plan_tool_call.args and plan_tool_call.args.get('action'):
                plan_args = plan_tool_call.args
                action = plan_args.get('action')
                reason = plan_args.get('reason', 'No reason provided.')
                print(f"Query Planner decided: {action}. Reason: {reason}")

                if action == 'REPLACE':
                    final_filters = current_filters
                else: # MERGE
                    final_filters.update(current_filters)
            else:
                # SAFE DEFAULT: If the AI fails to provide a clear plan, log it and make a safe choice.
                # If the user is adding info, the safest choice is to MERGE.
                print("Query Planner Warning: AI did not return a valid plan. Defaulting to MERGE.")
                final_filters.update(current_filters)

        except Exception as e:
            print(f"Query Planner Error: {e}. Defaulting to REPLACE on critical error.")
            final_filters = current_filters
    
    print(f"Final Filters to be applied: {final_filters}")

    # ... The rest of the file is unchanged ...

    ranking_priorities = []
    try:
        ranking_prompt = f"""
        Analyze the user's intent from the history and latest query.
        Your output MUST be a valid JSON list of strings and nothing else.
        The list can contain 'sentiment_dentist_skill', 'sentiment_cost_value', 'sentiment_convenience'.
        - For complex services ('implant', 'braces', 'root canal'), prioritize 'sentiment_dentist_skill'.
        - For cosmetic services ('whitening', 'veneers'), prioritize 'sentiment_cost_value'.
        - For location queries ('near', 'in'), prioritize 'sentiment_convenience'.
        - If the intent is ambiguous or general, return an empty list [].

        History:
        {conversation_history_for_prompt}
        Latest Query: "{latest_user_message}"

        Respond with ONLY the JSON list. Do not add any other text or markdown.
        """
        ranking_response = ranking_brain_model.generate_content(ranking_prompt)
        json_text = ranking_response.text
        start_index = json_text.find('[')
        end_index = json_text.rfind(']')
        if start_index != -1 and end_index != -1:
            clean_json_text = json_text[start_index:end_index+1]
            ranking_priorities = json.loads(clean_json_text)
        print(f"Ranking Brain determined priorities: {ranking_priorities}")
    except Exception as e:
        print(f"Ranking Brain Error: {e}")
        ranking_priorities = []

    candidate_clinics = []
    try:
        query_embedding_response = genai.embed_content(model=embedding_model, content=latest_user_message, task_type="RETRIEVAL_QUERY")
        query_embedding_list = query_embedding_response['embedding']
        query_embedding_text = "[" + ",".join(map(str, query_embedding_list)) + "]"
        db_response = supabase.rpc('match_clinics_simple', {'query_embedding_text': query_embedding_text, 'match_count': 75}).execute()
        candidate_clinics = db_response.data if db_response.data else []
        print(f"Found {len(candidate_clinics)} candidates from semantic search.")
    except Exception as e:
        print(f"Semantic search DB function error: {e}")

    qualified_clinics = []
    if candidate_clinics:
        for clinic in candidate_clinics:
            if clinic.get('rating', 0) >= 4.5 and clinic.get('reviews', 0) >= 30:
                qualified_clinics.append(clinic)
        print(f"Found {len(qualified_clinics)} candidates after Quality Gate.")

        if final_filters:
            factually_filtered_clinics = []
            for clinic in qualified_clinics:
                match = True
                if final_filters.get('township') and final_filters.get('township').lower() not in clinic.get('address', '').lower():
                    match = False
                if final_filters.get('services'):
                    for service in final_filters.get('services'):
                        if not clinic.get(service, False):
                            match = False; break
                if match:
                    factually_filtered_clinics.append(clinic)
            qualified_clinics = factually_filtered_clinics
            print(f"Found {len(qualified_clinics)} after applying Factual Filters.")

    top_clinics = []
    if qualified_clinics:
        if ranking_priorities:
            print(f"Applying SENTIMENT-FIRST ranking with priorities: {ranking_priorities}")
            ranking_keys = ranking_priorities + ['rating', 'reviews']
            unique_keys = list(dict.fromkeys(ranking_keys))
            ranked_clinics = sorted(qualified_clinics, key=lambda x: tuple(x.get(key, 0) or 0 for key in unique_keys), reverse=True)
        else:
            print("Applying OBJECTIVE-FIRST weighted score.")
            max_reviews = max([c.get('reviews', 1) for c in qualified_clinics]) or 1
            for clinic in qualified_clinics:
                norm_rating = (clinic.get('rating', 0) - 1) / 4.0
                norm_reviews = np.log1p(clinic.get('reviews', 0)) / np.log1p(max_reviews)
                clinic['quality_score'] = (norm_rating * 0.65) + (norm_reviews * 0.35)
            ranked_clinics = sorted(qualified_clinics, key=lambda x: x.get('quality_score', 0), reverse=True)
        
        top_clinics = ranked_clinics[:3]
        print(f"Ranking complete. Top clinic: {top_clinics[0]['name'] if top_clinics else 'N/A'}")

    context = ""
    if top_clinics:
        clinic_data_for_prompt = []
        for clinic in top_clinics:
             clinic_info = { "name": clinic.get('name'), "address": clinic.get('address'), "rating": clinic.get('rating'), "reviews": clinic.get('reviews'), "website_url": clinic.get('website_url'), "operating_hours": clinic.get('operating_hours'),}
             clinic_data_for_prompt.append(clinic_info)
        context = json.dumps(clinic_data_for_prompt, indent=2)
    else:
        context = "I'm sorry, I could not find any clinics that matched your specific search criteria."

    augmented_prompt = f"""
    You are an expert dental clinic assistant. Your task is to generate a concise, data-driven response.
    Use the conversation history for context. Your primary goal is to answer the LATEST USER QUESTION.

    **CONVERSATION HISTORY:**
    {conversation_history_for_prompt}

    **DATABASE SEARCH RESULTS (Context for your answer):**
    ```json
    {context}
    ```
    
    **LATEST USER QUESTION:**
    "{latest_user_message}"

    ---
    **YOUR TASK:**
    - Answer the LATEST USER QUESTION.
    - If the question was a search, format your response like the example.
    - If the question was a follow-up, answer it naturally.

    **--- EXAMPLE RESPONSE FORMAT (for a search query) ---**
    Based on your criteria, here are my top recommendations:
    🏆 **Top Choice: JDT Dental**
    *   **Rating:** 4.9★ (1542 reviews)
    *   **Address:** ...
    *   **Why it's great:** ...
    ---
    """
    
    final_response = generation_model.generate_content(augmented_prompt)

    return {"response": final_response.text, "applied_filters": final_filters}