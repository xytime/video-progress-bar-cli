import os
import dashscope
from dashscope.utils.oss_utils import OssUtils
import requests

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")

def test_oss_url():
    print("=== Testing DashScope OSS Direct HTTPS URL ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    # 1. Get upload certificate
    res = OssUtils.get_upload_certificate(model="cosyvoice-v3-flash", api_key=dashscope.api_key)
    if res.status_code != 200:
        print(f"Failed to get certificate: {res.message}")
        return
        
    upload_info = res.output
    print("Upload Info:")
    for k, v in upload_info.items():
        if k not in ('oss_access_key_id', 'signature', 'policy'):
            print(f"  {k}: {v}")
            
    # 2. Upload the file
    print("\nUploading file...")
    oss_url, cert = OssUtils.upload(
        model="cosyvoice-v3-flash",
        file_path=ref_audio,
        api_key=dashscope.api_key,
        upload_certificate=upload_info
    )
    print(f"Returned OSS URL: {oss_url}")
    
    # 3. Construct HTTPS URL
    # Format of oss_url: oss://key
    key = oss_url.replace("oss://", "")
    host = upload_info["upload_host"]
    # Usually upload_host is like http://bucket.oss-cn-beijing.aliyuncs.com
    # We replace http:// with https:// for security
    if host.startswith("http://"):
        host = host.replace("http://", "https://")
    https_url = f"{host}/{key}"
    print(f"Constructed HTTPS URL: {https_url}")
    
    # 4. Check if it is accessible
    print("\nChecking if public-read is allowed...")
    response = requests.head(https_url)
    print(f"HTTP Status: {response.status_code}")
    if response.status_code == 200:
        print("Success! The OSS URL is public-read and fully accessible via HTTPS!")
    else:
        print("Failed: Private ACL. Headers:")
        print(response.headers)
        print(response.text if hasattr(response, 'text') else "")

if __name__ == "__main__":
    test_oss_url()
