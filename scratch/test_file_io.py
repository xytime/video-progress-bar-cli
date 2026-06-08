import requests

def test_file_io():
    print("=== Testing file.io Upload ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    with open(ref_audio, "rb") as f:
        files = {"file": f}
        # file.io deletes the file after 1 download or 1 day, which is perfect for temporary enrollment!
        response = requests.post("https://file.io", files=files)
        
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    test_file_io()
