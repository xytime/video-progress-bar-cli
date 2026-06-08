import requests

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"
headers = {"xi-api-key": API_KEY}

def test_endpoints():
    endpoints = [
        ("User Info", "https://api.elevenlabs.io/v1/user"),
        ("Voices List", "https://api.elevenlabs.io/v1/voices"),
        ("Models List", "https://api.elevenlabs.io/v1/models")
    ]
    
    for name, url in endpoints:
        print(f"=== Testing {name} ===")
        try:
            response = requests.get(url, headers=headers)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if name == "User Info":
                    print(f"User: {data.get('subscription')}")
                elif name == "Voices List":
                    print(f"Voices count: {len(data.get('voices', []))}")
                    for voice in data.get('voices', [])[:3]:
                        print(f"  Voice: {voice['name']} (ID: {voice['voice_id']})")
                elif name == "Models List":
                    print(f"Models: {[m['model_id'] for m in data]}")
            else:
                print(response.text)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_endpoints()
