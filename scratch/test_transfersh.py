import requests

def test_transfersh():
    print("=== Testing transfer.sh Upload ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    url = "https://transfer.sh/denzel_ref.wav"
    try:
        with open(ref_audio, "rb") as f:
            response = requests.put(url, data=f)
        print(f"Status Code: {response.status_code}")
        print(f"Response URL: {response.text.strip()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_transfersh()
