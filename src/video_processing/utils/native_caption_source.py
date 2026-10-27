"""原字幕保留：人工确认或宿主验证的自动决定，交付片与源片逐字节相同。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 2.0.0 | 2026-10-27 | Codex | 单片凭证、自动识别证据及历史凭证兼容，不伪造 ASS。 |
| 1.0.0 | 2026-10-27 | Codex | 摘要绑定用户确认、审查正文与原样交付，禁止泛化为字幕跳过开关。 |
"""
import json
from pathlib import Path
import shutil

from config.settings import settings
from .render_source_binding import digest
from .source_caption_contract import fingerprint, validate_decision


APPROVALS = Path(settings.project_root) / 'config/native_caption_sources.json'
LEGACY_APPROVALS = Path(settings.project_root) / 'config/native_caption_sources_legacy_v1.json'


def approved_entry(prefix: str) -> dict | None:
    if not APPROVALS.is_file():
        return None
    data = json.loads(APPROVALS.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise ValueError('原字幕保留清单版本无效')
    return data['sources'].get(prefix)


def _entry(prefix: str) -> dict:
    entry = approved_entry(prefix)
    if (not entry or not entry.get('user_confirmed') or not entry.get('review_text', '').strip()
            or not entry.get('source_sha256')):
        raise ValueError('缺少单片用户确认或内容审查正文')
    return entry


def receipt_path(vertical: Path) -> Path:
    return vertical.with_suffix('.native-captions.json')


def requested(vertical: Path) -> bool:
    """损坏凭证仍须进入验证分支，不能静默回退到陈旧的加字幕成片。"""
    return bool(approved_entry(vertical.stem.removesuffix('_vertical'))) or receipt_path(vertical).exists()


def _selected_entry(vertical: Path) -> tuple[str, dict]:
    prefix = vertical.stem.removesuffix('_vertical')
    if approved_entry(prefix):
        return 'manual', _entry(prefix)
    entry = validate_decision(vertical)
    if entry['decision'] != 'PRESERVE' or not entry['review_text'].strip():
        raise ValueError('原字幕自动识别未通过，不能原样交付')
    return 'automatic', entry


def preserved_source(vertical: Path, fallback: Path) -> Path:
    """准备及提交统一使用实际保留的裁剪源，路径必须位于本任务输出目录。"""
    if not receipt_path(vertical).exists():
        return fallback
    receipt = json.loads(receipt_path(vertical).read_text())
    path = Path(receipt.get('source_path', fallback))
    if not path.resolve().is_relative_to(vertical.parent.resolve()):
        raise ValueError('原字幕源文件不在任务输出目录')
    validate_preserved(vertical, path)
    return path


def validate_preserved(vertical: Path, source: Path | None = None) -> dict:
    prefix = vertical.stem.removesuffix('_vertical')
    if vertical.name != f'{prefix}_vertical.mp4':
        raise ValueError('原字幕保留只接受标准交付文件')
    mode, entry = _selected_entry(vertical)
    receipt = json.loads(receipt_path(vertical).read_text(encoding='utf-8'))
    if receipt.get('version') == 1 and mode == 'manual':
        approval_hash = digest(APPROVALS)
        # 历史提交的凭证保持原文件不变；只在旧快照与当前单片条目完全一致时兼容。
        if LEGACY_APPROVALS.is_file():
            legacy = json.loads(LEGACY_APPROVALS.read_text())
            if (legacy.get('sources', {}).get(prefix) == entry
                    and receipt.get('approval_sha256') == digest(LEGACY_APPROVALS)):
                approval_hash = digest(LEGACY_APPROVALS)
        expected = dict(version=1, mode='preserve_native_captions',
                        approval_sha256=approval_hash, source_sha256=entry['source_sha256'])
    else:
        expected = dict(version=2, mode='preserve_native_captions', authority=mode,
                        entry_sha256=fingerprint(entry), source_sha256=entry['source_sha256'],
                        source_path=receipt.get('source_path'))
        source_path = Path(receipt['source_path'])
        if (not source_path.is_absolute() or not source_path.resolve().is_relative_to(vertical.parent.resolve())
                or digest(source_path) != entry['source_sha256']):
            raise ValueError('原字幕源文件路径或摘要无效')
    if receipt != expected or digest(vertical) != entry['source_sha256']:
        raise ValueError('原字幕成片或确认凭证已变更')
    if source is not None and digest(source) != entry['source_sha256']:
        raise ValueError('原字幕保留源片与确认摘要不匹配')
    return entry


def preserve(source: Path, vertical: Path) -> None:
    prefix = vertical.stem.removesuffix('_vertical')
    mode, entry = _selected_entry(vertical)
    if (mode == 'manual' and source.stem != prefix) or digest(source) != entry['source_sha256']:
        raise ValueError('原字幕保留源片与确认摘要不匹配')
    if (vertical.name != f'{prefix}_vertical.mp4' or source.resolve() == vertical.resolve()
            or not source.resolve().is_relative_to(vertical.parent.resolve())):
        raise ValueError('原字幕交付路径无效')
    if receipt_path(vertical).exists():
        validate_preserved(vertical, source)
        return
    # 先验证源片再写入；原子替换避免留下半份交付文件。
    temporary = vertical.with_suffix('.native-pending.mp4')
    try:
        shutil.copyfile(source, temporary)
        if digest(temporary) != entry['source_sha256']:
            raise ValueError('原字幕复制摘要不匹配')
        temporary.replace(vertical)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = dict(version=2, mode='preserve_native_captions', authority=mode,
                   entry_sha256=fingerprint(entry), source_sha256=entry['source_sha256'],
                   source_path=str(source.resolve()))
    destination = receipt_path(vertical)
    pending = destination.with_suffix('.pending.json')
    pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(destination)
    validate_preserved(vertical, source)


def review_text(vertical: Path) -> str:
    return validate_preserved(vertical)['review_text']
