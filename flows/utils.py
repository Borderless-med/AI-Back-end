def derive_clinic_tags(clinic: dict) -> list:
    tags = []
    if clinic.get('rating', 0) >= 4.8:
        tags.append('Top Rated')
    if clinic.get('reviews', 0) >= 100:
        tags.append('High Review Volume')
    if clinic.get('dental_implant'):
        tags.append('Implant Focus')
    if clinic.get('porcelain_veneers') or clinic.get('composite_veneers'):
        tags.append('Cosmetic Friendly')
    return tags


def get_disclaimer() -> str:
    return ("\n\nDisclaimer: This information is general and educational. It is not a diagnosis or treatment plan. "
            "Please consult a qualified dentist for personal medical advice.")
