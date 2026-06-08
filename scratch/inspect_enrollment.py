import dashscope
from dashscope.audio.tts_v2 import VoiceEnrollmentService
import inspect

service = VoiceEnrollmentService()
print("=== Methods of VoiceEnrollmentService ===")
for name, member in inspect.getmembers(service, predicate=inspect.ismethod):
    print(f"Method: {name}")
    sig = inspect.signature(member)
    print(f"  Signature: {sig}")
