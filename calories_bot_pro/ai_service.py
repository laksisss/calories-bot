import anthropic
import json
from config import ANTHROPIC_API_KEY, CLAUDE_TEXT_MODEL, CLAUDE_VISION_MODEL
from utils.validator import validate_meal_data

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

async def analyze_text_meal(text: str):
    prompt = f"""Проанализируй описание еды и верни JSON с КБЖУ.
    
Описание: {text}

Верни JSON в формате:
{{
    "name": "название блюда",
    "weight": 100,
    "calories": 250.5,
    "protein": 15.2,
    "fat": 8.3,
    "carbs": 30.1
}}

Если указано несколько продуктов, верни массив.
Вес указывай в граммах. Если вес не указан, оцени примерно.
"""
    message = client.messages.create(
        model=CLAUDE_TEXT_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    response_text = message.content[0].text
    try:
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        if start != -1 and end != 0:
            json_str = response_text[start:end]
            data = json.loads(json_str)
            return validate_meal_data(data)
    except:
        pass
    return None

async def analyze_photo(image_base64: str, media_type: str = "image/jpeg"):
    prompt = """Проанализируй фото еды и определи:
1. Название блюда
2. Примерный вес порции в граммах
3. КБЖУ на всю порцию

Верни JSON в формате:
{
    "name": "название блюда",
    "weight": 250,
    "calories": 450.5,
    "protein": 25.2,
    "fat": 18.3,
    "carbs": 45.1
}

Если на фото несколько блюд, верни массив.
"""
    message = client.messages.create(
        model=CLAUDE_VISION_MODEL,
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_base64
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }]
    )
    response_text = message.content[0].text
    try:
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        if start != -1 and end != 0:
            json_str = response_text[start:end]
            data = json.loads(json_str)
            return validate_meal_data(data)
    except:
        pass
    return None
