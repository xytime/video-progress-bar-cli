import os
import time
import requests

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"
SOURCE_FILE = "output/Bezos_AI_1min.mp4"
OUTPUT_FILE = "output/Bezos_AI_1min_dubbed_zh.mp4"

def run_dubbing_bezos():
    print(f"=== Jeff Bezos 1min ElevenLabs AI Dubbing ===")
    print(f"Source file: {SOURCE_FILE}")
    print(f"Output file: {OUTPUT_FILE}")
    
    if not os.path.exists(SOURCE_FILE):
        print(f"Error: Source file {SOURCE_FILE} does not exist.")
        return
        
    headers = {
        "xi-api-key": API_KEY
    }
    
    # 1. Submit Dubbing Task
    print("\n[1/3] Submitting dubbing task to ElevenLabs...")
    url_submit = "https://api.elevenlabs.io/v1/dubbing"
    
    data = {
        "target_lang": "zh",
        "source_lang": "en",
        "name": "Jeff_Bezos_1min_Dub",
        "num_speakers": 1,
        "watermark": True
    }
    
    try:
        with open(SOURCE_FILE, "rb") as f:
            files = {
                "file": (os.path.basename(SOURCE_FILE), f, "video/mp4")
            }
            response = requests.post(url_submit, headers=headers, data=data, files=files)
            
        if response.status_code != 200:
            print(f"Submission failed: Status {response.status_code}")
            print(response.text)
            return
            
        res_json = response.json()
        dubbing_id = res_json.get("dubbing_id")
        print(f"Successfully submitted! Dubbing ID: {dubbing_id}")
        
    except Exception as e:
        print(f"Exception during submission: {e}")
        return

    # 2. Polling status
    print("\n[2/3] Polling status...")
    url_status = f"https://api.elevenlabs.io/v1/dubbing/{dubbing_id}"
    
    start_time = time.time()
    while True:
        try:
            response = requests.get(url_status, headers=headers)
            if response.status_code != 200:
                print(f"Failed to get status: Status {response.status_code}")
                print(response.text)
                return
                
            status_json = response.json()
            status = status_json.get("status")
            print(f"Current status: {status} (elapsed: {int(time.time() - start_time)}s)")
            
            if status == "dubbed":
                print("Dubbing completed successfully!")
                break
            elif status == "failed":
                print("Dubbing failed on ElevenLabs side.")
                print(f"Details: {status_json}")
                return
            elif status == "processing" or status == "nearing_completion" or status == "preparing" or status == "dubbing":
                pass
            else:
                print(f"Unknown status: {status}")
                
            time.sleep(5)
            
        except Exception as e:
            print(f"Exception during polling: {e}")
            return

    # 3. Download the result file
    print("\n[3/3] Downloading dubbed video...")
    url_download = f"https://api.elevenlabs.io/v1/dubbing/{dubbing_id}/audio/zh"
    
    try:
        response = requests.get(url_download, headers=headers, stream=True)
        if response.status_code != 200:
            print(f"Failed to download dubbed file: Status {response.status_code}")
            print(response.text)
            return
            
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
        print(f"Download complete! Saved to: {OUTPUT_FILE}")
        print(f"File size: {os.path.getsize(OUTPUT_FILE)} bytes")
        
    except Exception as e:
        print(f"Exception during download: {e}")
        return

if __name__ == "__main__":
    run_dubbing_bezos()
