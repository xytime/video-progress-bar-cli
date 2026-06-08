import requests

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"

def list_all_voices():
    headers = {"xi-api-key": API_KEY}
    url = "https://api.elevenlabs.io/v1/voices"
    
    print("=== Listing All Added Voices ===")
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            voices = data.get('voices', [])
            print(f"Total voices: {len(voices)}")
            for idx, voice in enumerate(voices):
                print(f"{idx+1}. {voice['name']} (ID: {voice['voice_id']}) - Category: {voice.get('category')}")
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_all_voices()
