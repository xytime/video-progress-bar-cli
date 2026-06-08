import inspect
from dashscope.audio.tts_v2 import VoiceEnrollmentService

source = inspect.getsource(VoiceEnrollmentService.create_voice)
print(source)
