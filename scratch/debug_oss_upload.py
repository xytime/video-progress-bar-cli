import os
import dashscope
from dashscope.utils.oss_utils import upload_file
import traceback

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")

def debug_upload():
    print("=== Debugging OSS Upload ===")
    ref_audio = "scratch/denzel_ref.wav"
    print(f"File exists: {os.path.exists(ref_audio)}")
    print(f"File size: {os.path.getsize(ref_audio)} bytes")
    
    file_url = f"file://{os.path.abspath(ref_audio)}"
    try:
        url = upload_file(model="cosyvoice-v3-flash", upload_path=file_url, api_key=dashscope.api_key)
        print(f"Result URL: {url}")
    except Exception as e:
        print("Exception raised:")
        traceback.print_exc()

if __name__ == "__main__":
    debug_upload()
