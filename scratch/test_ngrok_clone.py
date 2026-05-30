import os
import time
import json
import socket
import subprocess
import requests
import dashscope
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer

# Configure dashscope API key
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def run_ngrok_test():
    print("=== Testing CosyVoice Voice Enrollment via Local HTTP Server & Ngrok Tunnel ===")
    
    ref_audio = "scratch/denzel_ref.wav"
    if not os.path.exists(ref_audio):
        print("Extracting audio from video...")
        cmd = [
            "ffmpeg", "-y", "-i", "output/XcSdPK5Xwbk.mp4",
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            ref_audio
        ]
        subprocess.run(cmd, check=True)
        print("Audio extracted successfully.")

    # 1. Find a free port
    port = find_free_port()
    print(f"Using free port: {port}")

    # 2. Start HTTP server in the workspace root
    # This will serve files from the current working directory, so scratch/denzel_ref.wav
    # will be accessible at http://127.0.0.1:{port}/scratch/denzel_ref.wav
    print("Starting python HTTP server...")
    http_server = subprocess.Popen(
        ["python3", "-m", "http.server", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1) # wait for server to start

    # 3. Start ngrok
    print("Starting ngrok tunnel...")
    ngrok_process = subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    public_url = None
    # Poll ngrok local API to get the public URL
    print("Waiting for ngrok to establish tunnel...")
    for _ in range(15):
        try:
            res = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
            if res.status_code == 200:
                data = res.json()
                tunnels = data.get("tunnels", [])
                for t in tunnels:
                    if t.get("proto") == "https":
                        public_url = t.get("public_url")
                        break
                if public_url:
                    break
        except Exception:
            pass
        time.sleep(1)

    if not public_url:
        print("Failed to get ngrok public URL. Is ngrok configured and running?")
        http_server.terminate()
        ngrok_process.terminate()
        return

    # Check if there is a trailing slash
    if not public_url.endswith("/"):
        public_url += "/"
    file_url = f"{public_url}scratch/denzel_ref.wav"
    print(f"Ngrok Public File URL: {file_url}")

    # Test accessing it locally via the public URL to ensure it works
    try:
        head_res = requests.head(file_url, timeout=5)
        print(f"Local test access HTTP status: {head_res.status_code}")
    except Exception as e:
        print(f"Local test access failed: {e}")

    # 4. Create Custom Voice
    voice_id = None
    print("Enrolling voice using Ngrok public url...")
    try:
        service = VoiceEnrollmentService()
        voice_id = service.create_voice(
            target_model="cosyvoice-v3-flash",
            prefix="denzel",
            url=file_url
        )
        print(f"Voice enrolled successfully! Voice ID: {voice_id}")
    except Exception as e:
        print(f"Voice enrollment failed: {e}")

    # 5. Clean up background processes
    print("Shutting down HTTP server and ngrok...")
    http_server.terminate()
    ngrok_process.terminate()
    http_server.wait()
    ngrok_process.wait()
    
    return voice_id

if __name__ == "__main__":
    run_ngrok_test()
