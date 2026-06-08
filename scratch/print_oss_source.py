import inspect
import dashscope.utils.oss_utils as oss_utils

source = inspect.getsource(oss_utils.upload_file)
print(source)
