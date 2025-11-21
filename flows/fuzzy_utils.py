from rapidfuzz import process, fuzz

def fuzzy_match(query: str, candidates: list, threshold: int = 70):
    # candidates: list of FAQ question strings
    matches = process.extract(query, candidates, scorer=fuzz.token_set_ratio)
    for match, score, idx in matches:
        if score >= threshold:
            return idx  # Return index of best match
    return None
