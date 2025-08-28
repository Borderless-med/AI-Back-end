def handle_out_of_scope(latest_user_message: str):
    """
    Handles out-of-scope user queries with a cost-effective keyword router.
    """
    print("Executing Out-of-Scope flow...")
    
    # Convert message to lowercase for case-insensitive matching
    message = latest_user_message.lower()

    # Define keywords for different categories
    GREETING_KEYWORDS = ["how are you", "hello", "hi", "hey"]
    TRAVEL_KEYWORDS = ["map", "directions", "get to", "how to get", "travel", "traffic", "route", "long to get"]
    WEATHER_KEYWORDS = ["weather", "forecast", "temperature", "rain"]

    # --- Keyword-based routing ---
    
    # Check for greetings
    if any(keyword in message for keyword in GREETING_KEYWORDS):
        response_text = "Hello! I'm an AI assistant ready to help you with your dental clinic search. What can I do for you today?"
    
    # Check for travel questions
    elif any(keyword in message for keyword in TRAVEL_KEYWORDS):
        response_text = "I can't provide real-time travel information, but I recommend using Google Maps for the most accurate directions and traffic updates."

    # Check for weather questions
    elif any(keyword in message for keyword in WEATHER_KEYWORDS):
        response_text = "I am not able to provide weather forecasts. I would suggest checking a dedicated weather website or app."
    
    # Default fallback for all other out-of-scope questions
    else:
        response_text = "I am an AI Concierge designed to help with dental clinic information in Singapore and Johor Bahru. I'm sorry, but I can't help with that request."

    print(f"Out-of-Scope Response: {response_text}")
    
    return {
        "response": response_text
    }