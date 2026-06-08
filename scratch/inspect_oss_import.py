import dashscope

print("dashscope version:", getattr(dashscope, "__version__", "unknown"))

try:
    from dashscope import oss
    print("Import 'from dashscope import oss' succeeded.")
except Exception as e:
    print("Import 'from dashscope import oss' failed:", e)

try:
    import dashscope.common.utils as utils
    print("dashscope.common.utils members:", [x for x in dir(utils) if 'upload' in x.lower() or 'oss' in x.lower()])
except Exception as e:
    print("Import dashscope.common.utils failed:", e)

try:
    from dashscope.api_entities import dashscope_response
    print("dashscope_response members:", dir(dashscope_response))
except Exception as e:
    print("Import dashscope_response failed:", e)
