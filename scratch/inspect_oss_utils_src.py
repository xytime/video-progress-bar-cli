import inspect
import dashscope.utils.oss_utils as oss_utils

try:
    print(inspect.getsource(oss_utils.OssUtils))
except Exception as e:
    print("Error:", e)
