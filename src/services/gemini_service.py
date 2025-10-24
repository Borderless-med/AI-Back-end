# File: src/services/gemini_service.py (The FINAL version)

import os
import google.generativeai as genai

# This configures the client ONCE for your entire application
# Make sure GEMINI_API_KEY is set in your .env file
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Define ALL AI Models in one place ---

# Use a powerful model for the critical Gatekeeper task
gatekeeper_model = genai.GenerativeModel('models/gemini-pro-latest')

# Use a fast model for subsequent, simpler tasks
factual_brain_model = genai.GenerativeModel('models/gemini-2.5-flash')
ranking_brain_model = genai.GenerativeModel('models/gemini-2.5-flash')
generation_model = genai.GenerativeModel('models/gemini-2.5-flash') # For Q&A and other text generation

# The embedding model is just a string name, not a full model object
embedding_model_name = 'models/embedding-001'

# We can also add the models for your other flows here for consistency
booking_model = genai.GenerativeModel('models/gemini-2.5-flash')
outofscope_model = genai.GenerativeModel('models/gemini-2.5-flash')
remember_model = genai.GenerativeModel('models/gemini-2.5-flash')
qna_model = generation_model # The Q&A model is the same as the general generation model

print("✅ Centralized Gemini Service Initialized Successfully")