import requests
import json

# --- The URL of our local server ---
url = "http://127.0.0.1:8000/chat"

# --- The Test Query ---
user_message = "how are you today?"

# --- The JSON Payload ---
payload = {
    "history": [
        {"role": "user", "content": user_message}
    ],
    "applied_filters": {},
    "candidate_pool": [],
    "booking_context": {}
}

# --- A more robust way to send the request and print errors ---
try:
    print("--- Sending Request ---")
    
    # Send the request with a timeout
    response = requests.post(url, json=payload, timeout=10) # 10-second timeout
    
    print(f"Status Code: {response.status_code}")
    
    # This will raise an error if the status code is 4xx or 5xx
    response.raise_for_status()
    
    response_data = response.json()
    
    print("\n--- Chatbot Response ---")
    print(response_data.get("response"))
    print("\n--- Full JSON Output ---")
    print(json.dumps(response_data, indent=2))

except requests.exceptions.Timeout:
    print("\nERROR: The request timed out. The server is likely busy or has crashed.")
except requests.exceptions.ConnectionError:
    print("\nERROR: A connection could not be established. Is the server running?")
except requests.exceptions.RequestException as e:
    print(f"\nAN UNEXPECTED ERROR OCCURRED: {e}")