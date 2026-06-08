import os
import glob
import dashscope

path = os.path.dirname(dashscope.__file__)
print(f"dashscope package path: {path}")
py_files = glob.glob(os.path.join(path, "**/*.py"), recursive=True)
print(f"Found {len(py_files)} python files in dashscope.")

for f in py_files:
    try:
        with open(f, "r", encoding="utf-8") as file:
            content = file.read()
            if "upload" in content.lower():
                print(f"Found 'upload' in: {os.path.relpath(f, path)}")
            if "oss" in content.lower():
                # Print only first 3 matches to avoid cluttering
                print(f"Found 'oss' in: {os.path.relpath(f, path)}")
    except Exception as e:
        pass
