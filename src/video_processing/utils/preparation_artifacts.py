"""仅新预加工执行者使用的任务/尝试临时目录及生词兼容出口。

不修改 ASR 方法或其合同；兼容已存在的可选生词导出器，不引入该功能。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 尝试隔离系统临时音频及通用生词别名，只原子回写同片具名资产。 |
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile


@contextmanager
def isolated_caption_artifacts(processor, scope):
    if scope is None:
        yield
        return
    yid, slice_text = scope.key.rsplit(':', 1)
    index = int(slice_text)
    prefixes = {yid} if index == 0 else {f'{yid}_s{index}', f'{yid}_part{index}'}
    if processor.input_path.stem not in prefixes:
        raise ValueError('preparation source identity mismatch')
    root = Path(scope.output) / '.preparation-artifacts' / scope.key.replace(':', '_s') / scope.owner
    root.mkdir(parents=True, exist_ok=True)
    previous_temp = tempfile.tempdir
    tempfile.tempdir = str(root)
    exporter = getattr(processor, 'export_vocabulary_json', None)
    # 单任务独立进程内设置，不把默认输出目录或全局共享文件传给导出器。
    if exporter is not None:
        name = f'{processor.input_path.stem}_vocabulary.json'
        scoped_target = root / name
        output = Path(processor.output_path or processor.input_path)
        canonical_target = output.parent / name

        def export_scoped(segments, output_path=None):
            if output_path is not None and Path(output_path) != scoped_target:
                raise ValueError('unscoped vocabulary export is forbidden')
            result = exporter(segments, output_path=scoped_target)
            if result is None:
                return None
            if Path(result).resolve() != scoped_target.resolve():
                raise ValueError('vocabulary exporter ignored task output path')
            raw = scoped_target.read_bytes()
            payload = json.loads(raw)
            if payload.get('video_id') != processor.input_path.stem:
                raise ValueError('vocabulary identity mismatch')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile('wb', dir=canonical_target.parent,
                        prefix=f'.{name}-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(canonical_target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return result

        processor.export_vocabulary_json = export_scoped
    try:
        yield
    finally:
        if exporter is not None:
            processor.export_vocabulary_json = exporter
        tempfile.tempdir = previous_temp
