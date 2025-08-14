import os
from dotenv import load_dotenv
from supabase import create_client, Client
import csv

# --- Configuration ---
load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

# --- CRITICAL: SET THE PATH TO YOUR FINAL CSV FILE ---
# You MUST replace the placeholder below with the actual, full path to the
# CSV file you just downloaded from your master Google Sheet.
# The 'r' before the string is essential for Windows paths.
CSV_FILE_PATH = r"C:\GSP Personal\Post EndoMaster\Antler's Stuff\JB Dental clinics\SG-JB DENTAL - MASTER DATA & ANALYSIS - clinics_data_rows.csv"

def upload_final_data():
    print("--- Starting Final Data Upload Process ---")

    # Step 1: Clear the existing table to ensure a clean slate
    try:
        print("Step 1/3: Clearing existing data from 'clinics_data' table...")
        supabase.table("clinics_data").delete().neq("id", -1).execute()
        print("  -> Existing data cleared successfully.")
    except Exception as e:
        print(f"  -> ERROR clearing table: {e}")
        return

    # Step 2: Read the new, complete data from the CSV
    print(f"Step 2/3: Reading new data from: {CSV_FILE_PATH}")
    try:
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            all_rows_from_csv = list(csv_reader)
            total_rows = len(all_rows_from_csv)
            print(f"  -> Found {total_rows} rows to upload.")
    except FileNotFoundError:
        print(f"\n  -> FATAL ERROR: File not found at the specified path.")
        print("     Please make sure the CSV_FILE_PATH in the script is 100% correct.")
        return
    except Exception as e:
        print(f"\n  -> ERROR reading CSV file: {e}")
        return

    # Step 3: Upload the new data in batches
    print("Step 3/3: Uploading new data to Supabase in batches...")
    batch_size = 25
    for i in range(0, total_rows, batch_size):
        batch = all_rows_from_csv[i:i + batch_size]
        print(f"  - Uploading batch {int(i/batch_size) + 1} of {int(total_rows/batch_size) + 1}...")

        prepared_batch = []
        for row in batch:
            prepared_row = {}
            for key, value in row.items():
                if key not in ['embedding', 'embedding_arr']:
                    prepared_row[key] = value if value else None
            prepared_batch.append(prepared_row)
        
        try:
            supabase.table("clinics_data").upsert(prepared_batch).execute()
            print(f"    -> Batch successfully uploaded.")
        except Exception as e:
            print(f"    -> FATAL ERROR during batch upload: {e}")
            break

    print("\n--- Final Data Upload Process Complete! ---")

if __name__ == "__main__":
    upload_final_data()