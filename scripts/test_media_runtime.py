"""为离线媒体验收复制经官方散列核验的已安装 Whisper 模型。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-08 | Codex | 不导入模型或业务配置，解析已安装包元数据并拒绝缺失/损坏的缓存 |
"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlparse


MODEL_NAMES = ("tiny", "base")


def installed_models():
    spec = importlib.util.find_spec("whisper")
    if spec is None or not spec.origin:
        raise ValueError("未安装 Whisper；媒体验收未执行")
    content = Path(spec.origin).read_bytes()
    tree = ast.parse(content)
    registry = next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "_MODELS"
                            for target in node.targets))
    checksums = {}
    for name in MODEL_NAMES:
        url = urlparse(registry[name])
        parts = url.path.split("/")
        if (url.scheme != "https" or url.netloc != "openaipublic.azureedge.net"
                or parts[-1] != f"{name}.pt" or not re.fullmatch(r"[0-9a-f]{64}", parts[-2])):
            raise ValueError("未知 Whisper 模型元数据；拒绝猜测或下载")
        checksums[name] = parts[-2]
    return checksums, hashlib.sha256(content).hexdigest()


def copy_model(source, target, expected_sha256):
    """散列复制字节；错误副本不保留，源缓存不写入。"""
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"缺少常规离线模型文件 {source.name}；不下载、不跳过")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("wb") as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        target.unlink()
        raise ValueError(f"离线模型 {source.name} SHA256 不匹配；未启动测试")
    return {"source": str(source), "snapshot": str(target),
            "sha256": digest.hexdigest(), "bytes": target.stat().st_size}


def prepare_media(run_root, repo, evidence):
    checksums, metadata_sha256 = installed_models()
    source = (Path.home() / ".cache/whisper").resolve()
    destination = run_root / "cache/whisper"
    files = {name: copy_model(source / f"{name}.pt", destination / f"{name}.pt", checksum)
             for name, checksum in checksums.items()}
    runtime = {"models": files, "metadata_sha256": metadata_sha256,
               "model_cache": str(destination), "cpu_threads": 2}
    marker_path = repo / ".test-sandbox.json"
    marker = json.loads(marker_path.read_text())
    marker["media"] = runtime
    marker_path.write_text(json.dumps(marker))
    (evidence / "media-runtime.json").write_text(json.dumps(runtime, indent=2))
    return runtime
