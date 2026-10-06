"""只读 OpenType Unicode cmap；避免为缺字闸门升级生产依赖。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-07 | Codex | 支持 TrueType/OpenType/TTC 的 cmap 4/12 覆盖检查 |
"""
import struct

from .contracts import PipelineError


def missing_characters(path, text, face=0):
    data = path.read_bytes()
    def u16(offset):
        return struct.unpack_from('>H',data,offset)[0]
    def u32(offset):
        return struct.unpack_from('>I',data,offset)[0]
    try:
        base = 0
        if data[:4] == b'ttcf':
            if not 0 <= face < u32(8):
                raise ValueError('TTC face 不存在')
            base = u32(12 + 4*face)
        elif face != 0:
            raise ValueError('非 TTC face 必须为零')
        tables = {}
        for i in range(u16(base+4)):
            offset = base+12+i*16
            tables[data[offset:offset+4]] = u32(offset+8)
        cmap = tables[b'cmap']
        subtables = []
        for i in range(u16(cmap+2)):
            offset = cmap+4+i*8
            platform, encoding = u16(offset), u16(offset+2)
            if platform == 0 or (platform == 3 and encoding in {1,10}):
                table = cmap+u32(offset+4)
                if u16(table) in {4,12}:
                    subtables.append(table)
        if not subtables:
            raise ValueError('没有支持的 Unicode cmap')
        def has(code):
            for table in subtables:
                fmt = u16(table)
                if fmt == 12:
                    for i in range(u32(table+12)):
                        pos = table+16+i*12
                        start,end,glyph = u32(pos),u32(pos+4),u32(pos+8)
                        if start <= code <= end and glyph+code-start != 0:
                            return True
                elif code <= 0xffff:
                    count = u16(table+6)//2
                    ends = table+14
                    starts = ends+2*count+2
                    deltas = starts+2*count
                    ranges = deltas+2*count
                    for i in range(count):
                        start,end = u16(starts+2*i),u16(ends+2*i)
                        if start <= code <= end:
                            delta, shift = u16(deltas+2*i),u16(ranges+2*i)
                            if shift:
                                glyph = u16(ranges+2*i+shift+2*(code-start))
                                glyph = (glyph+delta)&0xffff if glyph else 0
                            else:
                                glyph = (code+delta)&0xffff
                            if glyph:
                                return True
            return False
        return sorted({c for c in text if not c.isspace() and not has(ord(c))})
    except (struct.error, KeyError, ValueError, IndexError) as exc:
        raise PipelineError('FONT_MISSING', f'字体 cmap 不可验证: {path.name}') from exc
