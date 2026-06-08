import requests

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"
VOICE_ID = "bhJUNIXWQQ94l8eI2VUf"

def inspect_voice():
    headers = {"xi-api-key": API_KEY}
    url = f"https://api.elevenlabs.io/v1/voices/{VOICE_ID}"
    
    print(f"=== Inspecting Voice: {VOICE_ID} ===")
    try:
        response = requests.get(url, headers=headers)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Voice Name: {data.get('name')}")
            print(f"Category: {data.get('category')}")
            print(f"Labels: {data.get('labels')}")
            print(f"Description: {data.get('description')}")
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_voice()
