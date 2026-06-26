import re

FOOD_DB = {
    "яйцо": {"calories": 157, "protein": 12.7, "fat": 10.9, "carbs": 0.7},
    "куриная грудка": {"calories": 165, "protein": 31, "fat": 3.6, "carbs": 0},
    "рис": {"calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28},
    "гречка": {"calories": 110, "protein": 4.2, "fat": 1.1, "carbs": 21},
    "творог": {"calories": 98, "protein": 18, "fat": 1.8, "carbs": 3.3},
    "овсянка": {"calories": 88, "protein": 3.5, "fat": 1.7, "carbs": 15},
    "банан": {"calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 23},
    "яблоко": {"calories": 52, "protein": 0.3, "fat": 0.2, "carbs": 14},
}

def parse_weight(text: str):
    patterns = [
        r'(\d+(?:[.,]\d+)?)\s*(?:г|грамм|гр)\b',
        r'(\d+(?:[.,]\d+)?)\s*(?:кг|килограмм)\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            weight = float(match.group(1).replace(',', '.'))
            if 'кг' in text.lower():
                weight *= 1000
            return weight
    return None

def find_in_local_db(text: str):
    text_lower = text.lower()
    for product, kbju in FOOD_DB.items():
        if product in text_lower:
            weight = parse_weight(text) or 100
            multiplier = weight / 100
            return {
                "name": product,
                "weight": weight,
                "calories": round(kbju["calories"] * multiplier, 1),
                "protein": round(kbju["protein"] * multiplier, 1),
                "fat": round(kbju["fat"] * multiplier, 1),
                "carbs": round(kbju["carbs"] * multiplier, 1),
            }
    return None
