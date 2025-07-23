import os
import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from supabase import create_client, Client
from enum import Enum
import json
from scipy.spatial.distance import cosine

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
    max_distance: float = Field(None, description="The maximum acceptable distance in kilometers from the CIQ.")
    min_dentist_skill: float = Field(None, description="Minimum score for dentist skill (1-10). Used for 'best dentist' or 'highly skilled'.")
    min_pain_management: float = Field(None, description="Minimum score for pain management. Used for 'painless' or 'gentle treatment'.")
    min_cost_value: float = Field(None, description="Minimum score for value. Used for 'affordable' or 'good price'.")
    min_staff_service: float = Field(None, description="Minimum score for staff. Used for 'friendly staff'.")
    min_ambiance_cleanliness: float = Field(None, description="Minimum score for ambiance. Used for 'clean clinic'.")
    min_convenience: float = Field(None, description="Minimum score for convenience. Used for 'on time' or 'easy to book'.")

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
        args = function_call.args; service_value = args.get("service")
        filters = { "township": args.get("township"), "min_rating": args.get("min_rating"), "service": service_value.value if isinstance(service_value, Enum) else service_value, "max_distance": args.get("max_distance"), "min_dentist_skill": args.get("min_dentist_skill"), "min_pain_management": args.get("min_pain_management"), "min_cost_value": args.get("min_cost_value"), "min_staff_service": args.get("min_staff_service"), "min_ambiance_cleanliness": args.get("min_ambiance_cleanliness"), "min_convenience": args.get("min_convenience") }
        print(f"AI-extracted filters: {filters}")
    except Exception as e:
        print(f"AI Planner Error: {e}."); filters = {}

    # STAGE 2: FACTUAL FILTERING
    query_builder = supabase.table('clinics_data').select('id, name, address, township, rating, reviews, embedding, distance, sentiment_overall, sentiment_dentist_skill, sentiment_pain_management, sentiment_cost_value, sentiment_staff_service, sentiment_ambiance_cleanliness, sentiment_convenience')
    if filters.get('township'): query_builder = query_builder.ilike('township', f"%{filters['township']}%")
    if filters.get('min_rating'): query_builder = query_builder.gte('rating', filters['min_rating'])
    if filters.get('service'): query_builder = query_builder.eq(filters['service'], True)
    if filters.get('max_distance'): query_builder = query_builder.lte('distance', filters['max_distance'])
    if filters.get('min_dentist_skill'): query_builder = query_builder.gte('sentiment_dentist_skill', filters['min_dentist_skill'])
    if filters.get('min_pain_management'): query_builder = query_builder.gte('sentiment_pain_management', filters['min_pain_management'])
    if filters.get('min_cost_value'): query_builder = query_builder.gte('sentiment_cost_value', filters['min_cost_value'])
    if filters.get('min_staff_service'): query_builder = query_builder.gte('sentiment_staff_service', filters['min_staff_service'])
    if filters.get('min_ambiance_cleanliness'): query_builder = query_builder.gte('sentiment_ambiance_cleanliness', filters['min_ambiance_cleanliness'])
    if filters.get('min_convenience'): query_builder = query_builder.gte('sentiment_convenience', filters['min_convenience'])

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
    else: top_5_clinics = []

    # STAGE 4: FINAL RESPONSE GENERATION
    context = ""
    if top_5_clinics:
        context += f"I searched using these filters: {filters}.\n"
        context += "Here are the most relevant clinics I found:\n"
        for clinic in top_5_clinics:
            context += f"- Name: {clinic.get('name')}, Township: {clinic.get('township')}, Rating: {clinic.get('rating')} stars, Distance: {clinic.get('distance')}km. Sentiment Scores -> Overall: {clinic.get('sentiment_overall')}, Staff: {clinic.get('sentiment_staff_service')}, Value: {clinic.get('sentiment_cost_value')}.\n"
    else:
        context = "I could not find any clinics that matched your specific criteria in the database."

    # <<< CORRECTED DISTANCE NOTE INSTRUCTION >>>
    augmented_prompt = f"""
    You are a helpful assistant for the SG-JB Dental Platform.
    Your task is to provide a conversational answer based ONLY on the context.
    The context contains a list of clinics found after applying specific filters. Use this data to justify your recommendations.
    Summarize the findings in a confident, helpful way.

    IMPORTANT RULE: If the user's question or the context provided mentions distance, you MUST append the following sentence to the VERY END of your response, on a new line:
    "(Please note: all distances are measured from the Johor Bahru CIQ complex.)"

    CONTEXT:
    {context}
    
    USER'S QUESTION:
    {query.message}
    """
    final_response = generation_model.generate_content(augmented_prompt)
    return {"response": final_response.text}