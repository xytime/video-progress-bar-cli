import dashscope.utils.oss_utils as oss_utils
import dashscope.files as files
import inspect

print("=== Methods in dashscope.utils.oss_utils ===")
for name, member in inspect.getmembers(oss_utils, predicate=inspect.isfunction):
    print(f"Function: {name} signature: {inspect.signature(member)}")

print("\n=== Methods in dashscope.files ===")
for name, member in inspect.getmembers(files, predicate=inspect.isclass):
    print(f"Class: {name}")
    for mname, mmember in inspect.getmembers(member, predicate=inspect.ismethod):
        print(f"  Method: {mname} signature: {inspect.signature(mmember)}")
