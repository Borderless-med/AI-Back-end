# flows/travel_flow.py (NEW REPLACEMENT CONTENT)

import os
import google.generativeai as genai
from supabase import Client
import logging

# It's good practice to get the model name from a central service if possible,
# but defining it here is also fine for this specific flow.
# Ensure this is the same model used for indexing: models/text-embedding-004
EMBEDDING_MODEL_NAME = "models/text-embedding-004"

# Configure the Gemini client (it should inherit the configuration from main.py,
# but explicit configuration is safer if this file is ever run standalone).
if not genai.get_model(EMBEDDING_MODEL_NAME):
    gemini_api_key = os.getenv("Gemini_API_Key")
    if not gemini_api_key:
        raise ValueError("Gemini_API_Key not found in .env file for travel_flow")
    genai.configure(api_key=gemini_api_key)

# This is the generation model that will answer the question based on the context.
# We can use a powerful model like Gemini 1.5 Pro or Flash.
generation_model = genai.GenerativeModel('gemini-1.5-flash')

def handle_travel_query(user_query: str, supabase_client: Client) -> dict | None:
    """
    Handles a user's travel-related query using a Semantic RAG approach.

    Args:
        user_query: The user's question.
        supabase_client: The initialized Supabase client instance.

    Returns:
        A dictionary with the response if a relevant FAQ is found, otherwise None.
    """
    print(f"[TRAVEL_FLOW] Received query: '{user_query}'")

    # --- Step 1: Generate an embedding for the user's query ---
    try:
        print("[TRAVEL_FLOW] Generating embedding for user query...")
        query_embedding = genai.embed_content(
            model=EMBEDDING_MODEL_NAME,
            content=user_query,
            task_type="RETRIEVAL_QUERY"  # Use 'RETRIEVAL_QUERY' for searching
        )['embedding']
        print("[TRAVEL_FLOW] Embedding generated successfully.")
    except Exception as e:
        logging.error(f"[TRAVEL_FLOW] Error generating embedding: {e}")
        return None  # Cannot proceed without an embedding

    # --- Step 2: Call the Supabase function to find matching FAQs ---
    # These parameters can be tuned.
    match_threshold = 0.78  # The minimum similarity score to consider a match.
    match_count = 3         # The maximum number of relevant documents to retrieve.

    try:
        print(f"[TRAVEL_FLOW] Calling Supabase 'match_faqs' function with threshold {match_threshold}...")
        # 'rpc' calls the database function we created
        response = supabase_client.rpc('match_faqs', {
            'query_embedding': query_embedding,
            'match_threshold': match_threshold,
            'match_count': match_count
        }).execute()
        
        matching_faqs = response.data
        print(f"[TRAVEL_FLOW] Found {len(matching_faqs)} potential matches.")

    except Exception as e:
        logging.error(f"[TRAVEL_FLOW] Error calling Supabase RPC: {e}")
        return None

    # --- Step 3: Check if any relevant documents were found ---
    if not matching_faqs:
        print("[TRAVEL_FLOW] No matches found above the threshold. Passing to next intent.")
        return None  # No good match, so let the main router handle it.

    # --- Step 4: Construct the prompt for the generation model ---
    # We combine the retrieved FAQs to form a "context" for the LLM.
    context = "\n".join([
        f"FAQ Question: {faq['question']}\nFAQ Answer: {faq['answer']}" for faq in matching_faqs
    ])

    prompt = f"""
    You are a helpful and friendly travel assistant for people travelling between Singapore and Johor Bahru (JB) for dental appointments.
    Your personality is concise, clear, and reassuring.

    Answer the user's question based ONLY on the context provided below.
    If the context does not contain enough information to answer the question, just say: "I'm sorry, I don't have specific information about that. I can only answer questions about travel between Singapore and JB for dental appointments."
    Do not make up any information that is not in the context.

    --- CONTEXT ---
    {context}
    --- END OF CONTEXT ---

    User's Question: {user_query}
    """

    # --- Step 5: Generate the final answer ---
    try:
        print("[TRAVEL_FLOW] Generating final answer with Gemini...")
        final_answer = generation_model.generate_content(prompt)
        print("[TRAVEL_FLOW] Final answer generated successfully.")
        
        # We return a dictionary in the format that main.py expects
        return {"response": final_answer.text}

    except Exception as e:
        logging.error(f"[TRAVEL_FLOW] Error generating final answer: {e}")
        return {"response": "I'm sorry, I encountered a technical issue while trying to answer your question. Please try again."}