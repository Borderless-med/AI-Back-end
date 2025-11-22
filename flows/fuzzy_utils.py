from rapidfuzz import process, fuzz

def fuzzy_match(query: str, candidates: list, threshold: int = 60):
    # candidates: list of FAQ question strings
    from logging import getLogger
    logger = getLogger("travel_flow")
    matches = process.extract(query, candidates, scorer=fuzz.token_set_ratio)
    logger.info(f"Fuzzy match scores: {[{'match': m, 'score': s, 'idx': i} for m, s, i in matches]}")
    logger.info(f"Fuzzy match threshold: {threshold}")
    # Enforce strict confidence threshold
    best_match = None
    best_score = -1
    best_idx = None
    for match, score, idx in matches:
        if score > best_score:
            best_score = score
            best_match = match
            best_idx = idx
    if best_score >= threshold:
        logger.info(f"Confident match found: '{best_match}' with score {best_score}. Returning FAQ.")
        return best_idx  # Return index of best match
    else:
        logger.info(f"No confident match. Best was '{best_match}' ({best_score}). Falling back to LLM.")
        return None
