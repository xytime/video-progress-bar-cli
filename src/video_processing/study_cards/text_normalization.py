"""逐词正文比较：兼容排印撇号，但不丢失数字或正文词。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-06 | Codex | 统一模型预检与渲染器的 Unicode 撇号归一化。 |
"""
import re
import unicodedata


def normalise_word(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(str.maketrans("’‘ʼ", "'''"))
    return re.sub(r"[^a-z0-9']+", "", value.lower())


def normalise_words(value: str) -> tuple[str, ...]:
    return tuple(word for token in value.split() if (word := normalise_word(token)))
