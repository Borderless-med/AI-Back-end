def handle_remember_session(session, latest_user_message):
    """
    Handle session memory and recall requests.
    This flow processes requests where users ask to remember, recall, or retrieve 
    information from previous conversations.
    """
    
    if not session:
        return {
            "response": "I don't have any previous conversation history to recall. This appears to be a new session. How can I help you today?"
        }
    
    # Get conversation context and state from session
    context = session.get("context", [])
    state = session.get("state", {})
    
    if not context or len(context) == 0:
        return {
            "response": "I don't see any previous conversation history in our session. How can I help you today?"
        }
    
    # Analyze what type of information user wants to remember
    message_lower = latest_user_message.lower()
    
    # Check if they're asking about clinic recommendations
    if any(word in message_lower for word in ['clinic', 'clinics', 'dentist', 'dental', 'location', 'recommend']):
        candidate_pool = state.get("candidate_pool", [])
        applied_filters = state.get("applied_filters", {})
        
        if candidate_pool:
            clinic_summary = f"In our previous conversation, I recommended {len(candidate_pool)} dental clinics"
            
            if applied_filters:
                filter_details = []
                for key, value in applied_filters.items():
                    if isinstance(value, list) and value:
                        filter_details.append(f"{key}: {', '.join(value)}")
                    elif value:
                        filter_details.append(f"{key}: {value}")
                
                if filter_details:
                    clinic_summary += f" based on your preferences: {'; '.join(filter_details)}"
            
            clinic_summary += ". Here are the clinics I found for you:\n\n"
            
            # List the clinics from candidate pool
            for i, clinic in enumerate(candidate_pool[:5], 1):  # Show max 5 clinics
                name = clinic.get('name', 'Unknown Clinic')
                location = clinic.get('location', 'Location not specified')
                clinic_summary += f"{i}. **{name}** - {location}\n"
            
            if len(candidate_pool) > 5:
                clinic_summary += f"\n... and {len(candidate_pool) - 5} more clinics."
            
            clinic_summary += "\n\nWould you like me to provide more details about any of these clinics or help you book an appointment?"
            
            return {
                "response": clinic_summary,
                "applied_filters": applied_filters,
                "candidate_pool": candidate_pool
            }
        else:
            return {
                "response": "I don't see any previous clinic recommendations in our session history. Would you like me to help you find dental clinics now?"
            }
    
    # Check if they're asking about booking context
    elif any(word in message_lower for word in ['book', 'appointment', 'schedule', 'reservation']):
        booking_context = state.get("booking_context", {})
        
        if booking_context:
            booking_summary = "From our previous conversation, here's your booking information:\n\n"
            
            if booking_context.get('selected_clinic'):
                booking_summary += f"**Selected Clinic:** {booking_context['selected_clinic']}\n"
            if booking_context.get('selected_service'):
                booking_summary += f"**Service:** {booking_context['selected_service']}\n"
            if booking_context.get('preferred_date'):
                booking_summary += f"**Preferred Date:** {booking_context['preferred_date']}\n"
            if booking_context.get('preferred_time'):
                booking_summary += f"**Preferred Time:** {booking_context['preferred_time']}\n"
            
            booking_summary += "\nWould you like to continue with this booking or make changes?"
            
            return {
                "response": booking_summary,
                "booking_context": booking_context
            }
        else:
            return {
                "response": "I don't see any previous booking information in our session. Would you like me to help you book an appointment now?"
            }
    
    # General conversation recall - provide a summary of recent context
    else:
        # Get the last few meaningful exchanges
        recent_context = context[-6:] if len(context) > 6 else context  # Last 3 exchanges (user + assistant)
        
        if recent_context:
            conversation_summary = "Here's a summary of our recent conversation:\n\n"
            
            for i, exchange in enumerate(recent_context, 1):
                role = exchange.get('role', 'unknown')
                content = exchange.get('content', '')
                
                if role == 'user':
                    conversation_summary += f"**You asked:** {content[:200]}{'...' if len(content) > 200 else ''}\n"
                elif role == 'assistant':
                    conversation_summary += f"**I responded:** {content[:200]}{'...' if len(content) > 200 else ''}\n\n"
            
            conversation_summary += "Is there something specific from our conversation you'd like me to elaborate on?"
            
            return {
                "response": conversation_summary
            }
        else:
            return {
                "response": "I don't have enough conversation history to provide a meaningful summary. How can I help you today?"
            }