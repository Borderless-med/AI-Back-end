# indexing_script.py

import os
import pandas as pd
import google.generativeai as genai
from supabase import create_client, Client
from dotenv import load_dotenv
import time

# --- 1. LOAD ENVIRONMENT VARIABLES AND INITIALIZE CLIENTS ---
print("Loading environment variables and initializing clients...")
load_dotenv()

# Load Google API Key and configure Gemini
gemini_api_key = os.getenv("GEMINI_API_KEY")
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file")
genai.configure(api_key=gemini_api_key)

# Load Supabase credentials and create client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("supabase_URL or Key not found in .env file")
supabase: Client = create_client(supabase_url, supabase_key)

print("Clients initialized successfully.")

# --- 2. LOAD THE FAQ DATA FROM CSV ---
# Using the exact file path you provided earlier.
csv_file_path = r"C:\GSP Personal\Post EndoMaster\Antler's Stuff\JB Dental clinics\sg-jb-chatbot-LATEST\data\travel\faq_trimmed_embedding.csv"

try:
    print(f"Loading FAQ data from '{csv_file_path}'...")
    df = pd.read_csv(csv_file_path, encoding='latin-1')
    df['id'] = df['id'].astype(int) # Ensure the 'id' column is treated as an integer
    df = df.where(pd.notna(df), None)
    print(f"Successfully loaded {len(df)} FAQs from the CSV file.")
except FileNotFoundError:
    print(f"Error: File not found at '{csv_file_path}'. Please double-check the path.")
    exit()

# --- 3. GENERATE EMBEDDINGS AND UPSERT TO SUPABASE ---
table_name = "faqs_semantic"
batch_size = 50 # Process in batches to be respectful of API rate limits

print(f"Starting the process of embedding and upserting to Supabase table: '{table_name}'")

for start_index in range(0, len(df), batch_size):
    end_index = start_index + batch_size
    batch_df = df.iloc[start_index:end_index]
    
    print(f"\nProcessing batch: FAQs {start_index + 1} to {min(end_index, len(df))}...")

    texts_to_embed = batch_df['question'].tolist()
    
    try:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=texts_to_embed,
            task_type="RETRIEVAL_DOCUMENT"
        )
        embeddings = result['embedding']
        print(f"Successfully generated {len(embeddings)} embeddings for this batch.")
    except Exception as e:
        print(f"An error occurred while generating embeddings: {e}")
        continue

    records_to_upsert = []
    for i, row in batch_df.iterrows():
        record = {
            'id': int(row['id']),
            'question': row['question'],
            'answer': row['answer'],
            'category': row.get('category'),
            'last_updated': row.get('last_updated'),
            'embedding': embeddings[i - start_index]
        }
        records_to_upsert.append(record)

    try:
        supabase.table(table_name).upsert(records_to_upsert).execute()
        print(f"Successfully upserted {len(records_to_upsert)} records to Supabase.")
    except Exception as e:
        print(f"An error occurred during Supabase upsert: {e}")

    time.sleep(1)

print("\n--- Process Complete ---")
print("All FAQs have been processed and stored in Supabase with their embeddings.")