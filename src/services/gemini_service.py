# File: src/services/gemini_service.py

import os
import google.generativeai as genai

# 1. Configure the client
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Define ALL AI Models (Based on your available list) ---

# BRAIN A: The "Smart" Gatekeeper (High Reasoning)
# Use 2.5 Pro for complex logic and routing.
gatekeeper_model = genai.GenerativeModel('models/gemini-2.5-pro')

# BRAIN B: The "Fast/Accurate" Workers
# Use 2.5 Pro for factual extraction and ranking; 2.5 Flash for final text generation.
factual_brain_model = genai.GenerativeModel('models/gemini-2.5-pro')
ranking_brain_model = genai.GenerativeModel('models/gemini-2.5-pro')
generation_model = genai.GenerativeModel('models/gemini-2.5-flash') 

# BRAIN C: The "Eyes" (Embeddings)
# We use text-embedding-004 (768 dimensions) as per your Semantic RAG upgrade.
embedding_model_name = 'models/text-embedding-004'

# --- Auxiliary Models (mapped to the Fast Brain) ---
booking_model = genai.GenerativeModel('models/gemini-2.5-flash')
outofscope_model = genai.GenerativeModel('models/gemini-2.5-flash')
remember_model = genai.GenerativeModel('models/gemini-2.5-flash')

# QnA uses the general generation model
qna_model = generation_model 

print("✅ Gemini Service: 2.5-Pro (logic) / 2.5-Flash (chat) / text-embedding-004 (embeddings)")