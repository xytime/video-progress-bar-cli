import requests

def test_catbox():
    print("=== Testing Catbox Upload ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    url = "https://catbox.moe/user/api.php"
    data = {
        "reqtype": "fileupload"
    }
    with open(ref_audio, "rb") as f:
        files = {
            "fileToUpload": (ref_audio, f, "audio/wav")
        }
        response = requests.post(url, data=data, files=files)
        
    print(f"Status Code: {response.status_code}")
    print(f"Response URL: {response.text.strip()}")

if __name__ == "__main__":
    test_catbox()
