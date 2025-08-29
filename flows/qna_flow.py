import google.generativeai as genai

def handle_qna(latest_user_message: str, generation_model: genai.GenerativeModel):
    """
    Handles general dental health questions.
    """
    print("Executing Q&A flow...")
    qna_prompt = f"""
    You are a helpful AI dental assistant for the SG-JB Dental platform. Your primary goal is to answer the user's question clearly and concisely.

    **IMPORTANT RULES:**
    1.  **Do Not Give Medical Advice:** You must not diagnose, treat, or give prescriptive advice.
    2.  **Include a Disclaimer:** Always end your response with a clear disclaimer advising the user to consult a qualified dentist for personal medical advice.
    3.  **Guide the User:** After the disclaimer, gently guide the user back to the app's main purpose by asking if they need help finding a clinic for the topic they asked about.

    **User's Question:** "{latest_user_message}"
    """
    try:
        ai_response = generation_model.generate_content(qna_prompt)
        follow_up_question = "\n\nWould you like me to help you find a clinic that can assist with this?"
        full_response = ai_response.text + follow_up_question
        print(f"Q&A AI Response: {full_response}")
        return {"response": full_response}
    except Exception as e:
        print(f"Q&A Flow Error: {e}")
        return {"response": "I'm sorry, I encountered an error while trying to answer your question. Please try again."}


