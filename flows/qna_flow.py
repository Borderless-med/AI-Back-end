# flows/qna_flow.py

def handle_qna(latest_user_message, generation_model):
    """
    Handles general dental health questions.
    """
    print("Executing Q&A Flow...")

    # Create a specific persona and instructions for the AI
    prompt = f"""
    You are a helpful AI dental assistant for the SG-JB Dental platform. 
    Your role is to answer the user's general question about dental health clearly and concisely.

    **IMPORTANT RULES:**
    1.  You MUST NOT provide medical advice.
    2.  Your response MUST end with a disclaimer advising the user to consult a qualified dentist for any personal health concerns.
    3.  After the disclaimer, you MUST ask a follow-up question to guide the user back to the main purpose of the application. For example: "Would you like me to help you find a clinic that can assist with this?"

    **User's Question:**
    "{latest_user_message}"
    """

    try:
        ai_response = generation_model.generate_content(prompt)
        response_text = ai_response.text
    except Exception as e:
        print(f"Q&A Flow Error: {e}")
        response_text = "I'm sorry, I encountered an error while trying to answer your question. Could you please try rephrasing it?"

    # The final response dictionary is returned to main.py
    # We return the existing filters and candidate_pool to preserve the user's context.
    return {
        "response": response_text
    }