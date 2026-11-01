"""只读核验字幕故障之后的同源完成回执与实际成片，不推断平台交付。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 对接普通字幕失败的完成证据；拒绝错源、旧回执、未完成及失配成片。 |
"""
import json
from pathlib import Path
import re
import time

from .render_source_binding import digest
from .subtitle_failure_receipt import read_bound_receipt, read_cached_quality_warning


def read_caption_completion(output_dir, prefix, failed_epoch):
    """仅识别正常产物目录；不存在或不完整的证据不证明恢复成功。"""
    if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix) or failed_epoch is None:
        return None
    root = Path(output_dir)
    source = root / 'original_video' / (prefix + '.mp4')
    output = root / (prefix + '_vertical.mp4')
    sidecar = output.with_name(output.name + '.subtitle-quality.json')
    directory = root / 'subtitle_recovery' / prefix
    try:
        if (directory.is_symlink() or not directory.is_dir() or sidecar.is_symlink()
                or not sidecar.is_file() or sidecar.stat().st_size > 65536):
            return None
        raw_render = sidecar.read_bytes()
        render = json.loads(raw_render)
        if not isinstance(render, dict) or render.get('state') != 'COMPLETE':
            return None
        # 重新核实当前模块/配置、ASR/完整译文、ASS、成片及不可变质量告警。
        read_cached_quality_warning(source, ass_path=source.with_suffix('.ass'), render_path=output)
        if sidecar.read_bytes() != raw_render or digest(output) != render['output_sha256']:
            return None
        identity = render['checkpoint']
        input_hash = digest(source)
        paths = sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:64]
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 65536:
                continue
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(raw, dict):
                    continue
                completed = raw['created_at']
                if (type(completed) not in (int, float)
                        or not failed_epoch < completed <= time.time()
                        or any(raw.get(key) != identity.get(key) for key in
                               ('input_sha256', 'asr_sha256', 'contract_sha256',
                                'checkpoint_path', 'checkpoint_sha256'))):
                    continue
                receipt = read_bound_receipt(path, attempt_id=raw['attempt_id'], input_path=source,
                    input_sha256=input_hash, started_at=completed, success=True)
                if receipt is not None:
                    return dict(completed_epoch=completed, input_sha256=input_hash,
                        output_sha256=render['output_sha256'], receipt_path=str(path),
                        receipt_sha256=digest(path))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None
