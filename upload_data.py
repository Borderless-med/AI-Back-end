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
# You MUST replace the placeholder below with the actual, full path to your CSV file.
# This is the "complete" CSV you downloaded from Google Sheets with all the sentiment scores.
CSV_FILE_PATH = "C:\GSP Personal\Post EndoMaster\Antler's Stuff\JB Dental clinics\clinics_data_rows with sentiment analysis.csv"

def upload_data_from_csv():
    print(f"Reading data from: {CSV_FILE_PATH}")

    try:
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            all_rows_from_csv = list(csv_reader)
            total_rows = len(all_rows_from_csv)
            print(f"Found {total_rows} rows to upload.")

            # We will upload the data in batches to be safe and efficient
            batch_size = 25
            for i in range(0, total_rows, batch_size):
                batch = all_rows_from_csv[i:i + batch_size]
                print(f"Preparing and uploading batch {int(i/batch_size) + 1}...")

                # This is the crucial step to prepare the data for Supabase
                prepared_batch = []
                for row in batch:
                    # Create a new dictionary to hold only the data we want to insert
                    prepared_row = {}
                    # Loop through all the keys from the CSV row
                    for key, value in row.items():
                        # We explicitly EXCLUDE the columns that the database auto-generates
                        if key not in ['embedding', 'embedding_arr']:
                            # If the value is an empty string, convert it to None (which becomes NULL)
                            prepared_row[key] = value if value != '' else None
                    
                    prepared_batch.append(prepared_row)

                # Use the library's insert command with our prepared data
                response = supabase.table("clinics_data").insert(prepared_batch).execute()
                
                # Check for errors in the response
                if response.data:
                    print(f"  -> Batch successfully uploaded.")
                else:
                    print(f"  -> ERROR uploading batch. Check response details.")
                    # If you need to debug, you can print the full response:
                    # print(response)

            print("\n--- Data upload complete! ---")

    except FileNotFoundError:
        print(f"\nFATAL ERROR: The file was not found at the specified path.")
        print("Please make sure the CSV_FILE_PATH in the script is 100% correct.")
        print("Hint: In your file explorer, right-click the file and choose 'Copy as path'.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

# --- Run the function ---
if __name__ == "__main__":
    upload_data_from_csv()