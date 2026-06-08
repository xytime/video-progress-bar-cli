import requests

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"
VOICE_ID = "XrExE9yKIg1WjnnlVkGX" # Matilda (Premade)

def test_tts():
    print(f"=== Testing TTS with Voice ID: {VOICE_ID} ===")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # Using eleven_multilingual_v2 model
    data = {
        "text": "每天早上告诉自己：今天将是美好的一天。积极的心态会像磁铁一样吸引好运。",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            output_file = "output/test_tts_matilda.mp3"
            with open(output_file, "wb") as f:
                f.write(response.content)
            print(f"Success! Saved test audio to {output_file}")
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_tts()
