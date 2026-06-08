import requests

def test_tmpfiles():
    print("=== Testing tmpfiles.org Upload ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    url = "https://tmpfiles.org/api/v1/upload"
    try:
        with open(ref_audio, "rb") as f:
            files = {"file": f}
            response = requests.post(url, files=files)
            
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            view_url = data.get("data", {}).get("url")
            print(f"View URL: {view_url}")
            # Convert to direct link
            if view_url and "tmpfiles.org/" in view_url:
                direct_url = view_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                print(f"Direct Link: {direct_url}")
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_tmpfiles()
