from rapidfuzz import process, fuzz

def fuzzy_match(query: str, candidates: list, threshold: int = 60):
    # candidates: list of FAQ question strings
    from logging import getLogger
    logger = getLogger("travel_flow")
    matches = process.extract(query, candidates, scorer=fuzz.token_set_ratio)
    logger.info(f"Fuzzy match scores: {[{'match': m, 'score': s, 'idx': i} for m, s, i in matches]}")
    for match, score, idx in matches:
        if score >= threshold:
            logger.info(f"Fuzzy match accepted: {match} (score: {score}, idx: {idx})")
            return idx  # Return index of best match
    logger.info("No fuzzy match above threshold.")
    return None
