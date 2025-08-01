# STAGE 1: THE "TWO BRAINS" PLANNER

# Brain #1: The Factual Brain extracts hard facts
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
    
# Brain #2: The Semantic Brain determines user's priorities
ranking_priority = []
try:
    ranking_prompt = f"""
    Analyze the user's query to determine their qualitative priorities for choosing a dental clinic.
    Return a JSON list of the most important sentiment columns to rank by, in order of priority.
    The available columns are: "sentiment_overall", "sentiment_dentist_skill", "sentiment_pain_management", "sentiment_cost_value", "sentiment_staff_service", "sentiment_ambiance_cleanliness", "sentiment_convenience".
    For "quality", prioritize "sentiment_dentist_skill". For "convenience", prioritize "sentiment_convenience". For "value" or "price", prioritize "sentiment_cost_value".
    USER QUERY: "{query.message}"
    """
    response = ranking_model.generate_content(ranking_prompt)
    # Clean up the response to get a valid JSON list
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
    query_embedding_response = genai.embed_content(model=embedding_model, content=query.message, task_type="RETRIEVAL_QUERY", output_dimensionality=768)
    query_embedding = query_embedding_response['embedding']
    db_response = supabase.rpc('match_clinics_simple', {'query_embedding': query_embedding, 'match_count': 25}).execute()
    candidate_clinics = db_response.data if db_response.data else []
    print(f"Found {len(candidate_clinics)} candidates from semantic search.")
except Exception as e:
    print(f"Semantic search DB function error: {e}")

# STAGE 3: FACTUAL FILTERING AND DYNAMIC RANKING
final_candidates = []
if candidate_clinics:
    if filters:
        for clinic in candidate_clinics:
            match = True
            if filters.get('township') and filters.get('township').lower() not in clinic.get('address', '').lower(): match = False
            if filters.get('min_rating') and (clinic.get('rating') is None or clinic.get('rating', 0) < filters.get('min_rating')): match = False
            if filters.get('services'):
                for service in filters.get('services'):
                    if not clinic.get(service, False): match = False; break
            if match: final_candidates.append(clinic)
    else:
        final_candidates = candidate_clinics
print(f"Found {len(final_candidates)} candidates after applying factual filters.")

top_5_clinics = []
if final_candidates:
    if not ranking_priority: # If semantic brain fails, use a default
        ranking_priority = ['sentiment_overall', 'rating', 'reviews']
    else:
        ranking_priority.extend(['rating', 'reviews'])
    ranking_priority = list(dict.fromkeys(ranking_priority))
    
    print(f"Final dynamic ranking priority: {ranking_priority}")
    ranked_clinics = sorted(final_candidates, key=lambda x: tuple(x.get(key, 0) or 0 for key in ranking_priority), reverse=True)
    top_5_clinics = ranked_clinics[:5]

# STAGE 4: FINAL RESPONSE GENERATION
context = ""
if top_5_clinics:
    context += "Here are the best matches I found for your request:\n"
    for clinic in top_5_clinics:
        context += f"- **{clinic.get('name')}**\n  - **Location:** {clinic.get('address')}\n  - **Rating:** {clinic.get('rating')} stars\n  - **Key Sentiments:** Overall: {clinic.get('sentiment_overall')}, Convenience: {clinic.get('sentiment_convenience')}, Skill: {clinic.get('sentiment_dentist_skill')}.\n"
else:
    context = "I'm sorry, I could not find any clinics that matched your search criteria in the database."

augmented_prompt = f"""
You are an expert dental clinic assistant. Your goal is to provide a helpful, data-driven recommendation based ONLY on the context provided.
Synthesize the data into a conversational answer. Explain WHY the clinics are a good match for the user's specific priorities.
**CRITICAL FORMATTING RULE: You MUST structure your response for maximum readability. Use a clear introductory sentence. Then, for each recommended clinic, start a new paragraph with the clinic's name in bold. Use bullet points or indented lines for key data like rating and specific sentiment scores.**
You must correctly interpret NULL/None values. If a sentiment score is not present, state that 'a specific score was not available'.
CONTEXT:
{context}

USER'S QUESTION:
{query.message}
"""
final_response = generation_model.generate_content(augmented_prompt)
return {"response": final_response.text}