# File: src/services/gemini_service.py

import os
import google.generativeai as genai

# 1. Configure the client
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Define ALL AI Models (Based on your available list) ---

# BRAIN A: The "Smart" Gatekeeper (High Reasoning)
# We use 2.5 Pro because it is the most capable model in your list for logic.
gatekeeper_model = genai.GenerativeModel('models/gemini-2.5-pro')

# BRAIN B: The "Fast" Workers (Speed & Cost Efficiency)
# We use 2.5 Flash as it is the standard fast model in your environment.
factual_brain_model = genai.GenerativeModel('models/gemini-2.5-flash')
ranking_brain_model = genai.GenerativeModel('models/gemini-2.5-flash')
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

print("✅ Centralized Gemini Service Initialized Successfully (Models: 2.5-Pro / 2.5-Flash / Text-004)")