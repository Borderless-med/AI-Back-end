# This script's only job is to connect to Supabase and
# print the exact column names of our table.

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# --- Load environment variables from the .env file ---
load_dotenv()

# --- Connect to Supabase ---
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

print("Connecting to Supabase to discover the schema of the 'clinics_data' table...")

try:
    # We fetch only ONE row to be efficient.
    # We only need one row to see all the column names.
    response = supabase.table("clinics_data").select("*").limit(1).execute()

    if response.data:
        # Get the first clinic's data
        first_clinic = response.data[0]
        
        # The .keys() method gives us a list of all column names.
        column_names = list(first_clinic.keys())
        
        print("\nSUCCESS! The schema has been discovered.")
        print("------------------------------------------")
        print("Your table 'clinics_data' has the following columns:")
        
        for column in column_names:
            print(f"- {column}")
        
        print("------------------------------------------")
        print("\nPlease use these exact column names in the next steps.")

    else:
        print("\nERROR: Could not fetch any data. Is the table 'clinics_data' empty or named differently?")

except Exception as e:
    print(f"\nAn error occurred while connecting or fetching data: {e}")