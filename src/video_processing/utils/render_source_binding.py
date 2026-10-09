"""绑定裁剪原片、零起点字幕与基础竖版，防二创误配未裁剪原片。

依赖：pipeline/processors → utils；只处理同一 output 根内的加工素材。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 增加源、字幕及成片摘要绑定，坏绑定拒绝回退误配。 |
"""
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def binding_path(vertical: Path) -> Path:
    return vertical.with_suffix(".source.json")


def bind_render_source(vertical: Path, original: Path, subtitles: Path) -> None:
    root = vertical.parent.resolve()
    stem = vertical.stem.removesuffix("_vertical")
    expected = root / "speech_opening" / stem / f"{stem}.mp4"
    if original.resolve() != expected or subtitles.resolve() != expected.with_suffix(".ass"):
        raise ValueError("裁剪绑定只能指向本片独立加工素材")
    payload = {"version": 1, "vertical_sha256": digest(vertical)}
    for name, path in (("original", original), ("subtitles", subtitles)):
        payload[name] = {"path": str(path.resolve().relative_to(root)), "sha256": digest(path)}
    destination = binding_path(vertical)
    pending = destination.with_suffix(".pending.json")
    pending.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pending.replace(destination)


def bound_render_inputs(vertical: Path) -> tuple[Path, Path] | None:
    """存在坏绑定时抛错，禁止悄悄使用另一条时间轴的原片。"""
    sidecar = binding_path(vertical)
    if not sidecar.is_file():
        return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or payload.get("vertical_sha256") != digest(vertical):
        raise ValueError("基础竖版与源绑定不匹配")
    root = vertical.parent.resolve()
    stem = vertical.stem.removesuffix("_vertical")
    original = root / "speech_opening" / stem / f"{stem}.mp4"
    result = []
    for name, expected in (("original", original), ("subtitles", original.with_suffix(".ass"))):
        entry = payload[name]
        if (root / entry["path"]).resolve() != expected or expected.resolve() != expected:
            raise ValueError("非法加工素材路径")
        if entry["sha256"] != digest(expected):
            raise ValueError("加工素材或字幕已变更")
        result.append(expected)
    return tuple(result)


def render_source_matches(vertical: Path, original: Path) -> bool:
    try:
        bound = bound_render_inputs(vertical)
        if bound is not None:
            return bound[0].resolve() == original.resolve()
        return original.parent.parent.name != "speech_opening"
    except (ValueError, OSError, KeyError, TypeError):
        return False
