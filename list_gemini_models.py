import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables (if using .env file)
load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=gemini_api_key)

models = genai.list_models()
for model in models:
    print(model.name)