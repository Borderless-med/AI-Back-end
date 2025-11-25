# ==============================================================================
# Out-of-Scope Flow Handler
#
# This file handles user queries that are not related to dental services.
# It uses a simple and cost-effective keyword-based approach to provide
# helpful redirection without calling the main LLM.
# ==============================================================================

def handle_out_of_scope(latest_user_message: str):
    """
    Handles out-of-scope user queries with a cost-effective keyword router.
    """
    print("Executing Out-of-Scope flow...")
    
    message = latest_user_message.lower()
    
    # Define keywords to check against the user's message
    GREETING_KEYWORDS = ["how are you", "hello", "hi", "hey"]
    WEATHER_KEYWORDS = ["weather", "forecast", "temperature", "rain"]

    # Check the message and provide a canned response
    if any(keyword in message for keyword in GREETING_KEYWORDS):
        response_text = "Hello! I'm an AI assistant ready to help you with your dental clinic search. What can I do for you today?"
    elif any(keyword in message for keyword in WEATHER_KEYWORDS):
        response_text = "I am not able to provide weather forecasts. I would suggest checking a dedicated weather website or app."
    else:
        # Default response for all other out-of-scope topics
        response_text = "I am an AI Concierge designed to help with dental clinic information in Singapore and Johor Bahru. I'm sorry, but I can't help with that request."

    print(f"Out-of-Scope Response: {response_text}")
    
    # Return the response in the standard dictionary format
    return {"response": response_text}