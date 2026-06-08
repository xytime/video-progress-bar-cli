import os
import json
import sys
from pathlib import Path

# Add src to path
_src = str(Path(__file__).parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from config.settings import settings

def test_gemini():
    api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    print(f"API KEY: {api_key[:10]}...{api_key[-5:]}")
    
    from google import genai as _genai
    from google.genai import types as _genai_types
    _client = _genai.Client(api_key=api_key)
    
    texts = [
        "Something is jamming GPS over Europe. Here's what we found.",
        "This is an international crisis of unprecedented proportions."
    ]
    
    prompt = (
        "You are an expert video subtitle translator and English educator. For each of the following English subtitle segments:\n"
        "1. Translate it into natural, native, and screen-friendly Chinese (zh-CN).\n"
        "2. Identify 1 to 2 key, academic, or difficult vocabulary words/phrases (CEFR B2-C2 or TOEFL/IELTS/GRE level) that are essential to the segment's meaning. Provide their concise Chinese definitions. Do not extract common/easy words. If there are no difficult words, leave the vocabulary dictionary empty.\n"
        "Return a JSON array of objects (one for each segment in the exact same order and count). Each object must contain:\n"
        "- \"translation\": string (Chinese translation)\n"
        "- \"vocab\": object (keys are the exact English words/phrases as they appear in the text, values are their concise Chinese translations)\n\n"
        f"Input segments:\n{json.dumps(texts, ensure_ascii=False)}"
    )
    
    try:
        response = _client.models.generate_content(
            model="models/gemini-3.5-flash",
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        print("Response Text:")
        print(response.text)
        result = json.loads(response.text)
        print("Parsed JSON:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error calling Gemini: {e}")

if __name__ == "__main__":
    test_gemini()
