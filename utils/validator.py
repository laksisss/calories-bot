def validate_meal_data(data: dict):
    required_fields = ["name", "weight", "calories", "protein", "fat", "carbs"]
    if not all(field in data for field in required_fields):
        return None
    try:
        weight = float(data["weight"])
        calories = float(data["calories"])
        protein = float(data["protein"])
        fat = float(data["fat"])
        carbs = float(data["carbs"])
        if not (10 <= weight <= 5000):
            return None
        if not (0 <= calories <= 3000):
            return None
        if not (0 <= protein <= 200):
            return None
        if not (0 <= fat <= 200):
            return None
        if not (0 <= carbs <= 500):
            return None
        return {
            "name": str(data["name"]),
            "weight": weight,
            "calories": calories,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
        }
    except (ValueError, TypeError):
        return None
