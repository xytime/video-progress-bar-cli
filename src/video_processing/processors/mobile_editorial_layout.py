"""已批准 mobile-2 画布：真实字体边界、平台安全区与手写圈画。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-09 | Codex | 从已确认样片提炼可复用绘制原语 |
"""
from pathlib import Path
from functools import lru_cache
import difflib
import math
import re
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
ASSETS = Path(__file__).resolve().parents[3] / "assets"
W, H, FPS = 1080, 1920, 30
VIDEO_Y, VIDEO_H = 440, 608
LEFT, RIGHT, SAFE_BOTTOM = 76, 960, 1480
PAPER, INK, COPPER = '#F2EEE5', '#191C1C', '#A76C43'
SERIF = ASSETS / 'fonts/SourceHanSerifCN-Medium.otf'
SANS = Path('/System/Library/Fonts/Hiragino Sans GB.ttc')
ENGLISH = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
QR = ASSETS / 'brand/05_qrcodes/liuwei-shikonghao-wechat-channels-code-source.jpeg'
@lru_cache(maxsize=64)
def font(size, kind='sans'):
    return ImageFont.truetype(str(SERIF if kind == 'serif' else ENGLISH if kind == 'en' else SANS), size)

def text(draw, value, xy, size, fill=INK, kind='sans'):
    draw.text(xy, value, font=font(size, kind), fill=fill, anchor='la')

def width(value, size, kind='sans'):
    return font(size, kind).getlength(value)

def brand(image, dark=False):
    draw = ImageDraw.Draw(image)
    color = PAPER if dark else INK
    # 延续已审阅的眼形识别元素，使用简单矢量线条避免缩小后霓虹细节糊成黑块。
    for control in (151,225):
        points=[(LEFT+84*t,188*(1-t)**2+2*control*(1-t)*t+188*t*t) for t in [i/40 for i in range(41)]]
        draw.line(points,fill=COPPER,width=4)
    draw.ellipse((LEFT+35,181,LEFT+49,195),fill=COPPER)
    text(draw, '六维时空号', (184, 153), 39, color, 'serif')
    value = '深度观察'
    text(draw, value, (RIGHT - width(value, 29), 188), 29, COPPER)
    slogan = '不同的视角，看见更大的世界。'
    text(draw, slogan, (RIGHT - width(slogan, 23), 228), 23, color)
    draw.line((LEFT, 272, RIGHT, 272), fill=COPPER if dark else '#C8B9A7', width=1)

def chinese_layout(image, value, xy, size, kind='sans', fill=INK, max_width=None, step=None, atoms=()):
    """返回精确绘制的字符位置，指读线复用同一组字宽，不采用猜测坐标。"""
    draw = ImageDraw.Draw(image)
    max_width = RIGHT - xy[0] if max_width is None else max_width
    step = round(size * 1.40) if step is None else step
    x, y = xy
    positions = []
    for index,char in enumerate(value):
        if char == '\n':
            x, y = xy[0], y + step
            continue
        length = width(char, size, kind)
        atom=next((a for a in sorted(atoms,key=len,reverse=True) if value.startswith(a,index)),None)
        if atom and width(atom,size,kind)<=max_width and x+width(atom,size,kind)>xy[0]+max_width:
            x,y=xy[0],y+step
        if x + length > xy[0] + max_width:
            x, y = xy[0], y + step
        text(draw, char, (x, y), size, fill, kind)
        if re.search(r'[\u3400-\u9fffA-Za-z0-9]', char):
            underline=y+font(size,kind).getbbox('国',anchor='la')[3]+8
            positions.append({'char': char, 'x': x, 'y': underline, 'width': length, 'line': y})
        x += length
    if y + size + 11 > SAFE_BOTTOM:
        raise ValueError(f'文字进入平台遮挡区：{value}')
    return positions

TRANSLITERATE = str.maketrans('這類項證據歡評論區說斷驗訊', '这类项证据欢评论区说断验讯')

def clean(value):
    return ''.join(c.lower() for c in value.translate(TRANSLITERATE) if c.isalnum())

def char_times(words, offset=0):
    result = []
    for word in words:
        value = clean(word['word'])
        if not value:
            continue
        duration = max(0, word['end'] - word['start'])
        for index, char in enumerate(value):
            result.append((char, word['start'] + duration * index / len(value) - offset,
                           word['start'] + duration * (index + 1) / len(value) - offset))
    return result

def align_positions(positions, words, offset=0):
    spoken = char_times(words, offset)
    expected = ''.join(clean(p['char']) for p in positions)
    actual = ''.join(item[0] for item in spoken)
    matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
    matched = {}
    for block in matcher.get_matching_blocks():
        for i in range(block.size):
            matched[block.a + i] = spoken[block.b + i][1:]
    if len(matched) / max(1, len(expected)) < .90:
        raise ValueError(f'语音与显示文案无法可靠对齐：{expected} / {actual}')
    # 未匹配字符保留原索引，在邻近真实匹配时间内插值，避免分页错位。
    result = []
    for index, position in enumerate(positions):
        if index in matched:
            start, end = matched[index]
        else:
            left = max((j for j in matched if j < index), default=None)
            right = min((j for j in matched if j > index), default=None)
            start = matched[left][1] if left is not None else matched[right][0]
            end = matched[right][0] if right is not None else start
            if right is not None and left is not None:
                step = max(0, end-start)/(right-left-1)
                start, end = start+step*(index-left-1), start+step*(index-left)
        result.append({**position, 'start': start, 'end': max(start,end)})
    return result

def pointer(image, positions, t, color=COPPER):
    """按ASR词时窗连续推进，同一行已经读到的内容留下细线；换行重新开始。"""
    draw = ImageDraw.Draw(image)
    progress = {}
    for p in positions:
        if t < p['start']:
            continue
        frac = 1 if t >= p['end'] or p['end'] <= p['start'] else (t - p['start']) / (p['end'] - p['start'])
        end_x = p['x'] + p['width'] * frac
        key = p['line']
        if key not in progress:
            progress[key] = [p['x'], end_x, p['y']]
        else:
            progress[key][1] = max(progress[key][1], end_x)
    for key, (x, end_x, y) in progress.items():
        draw.line((round(x), round(y), round(end_x), round(y)), fill=color, width=2)
    active = [p for p in positions if p['start'] <= t < p['end']]
    if active:
        p = active[-1]
        frac = (t - p['start']) / max(.001, p['end'] - p['start'])
        x, y = p['x'] + p['width'] * frac, p['y']
        draw.ellipse((x-3, y-3, x+3, y+3), fill=color)

def hand_circle(x, y, value, size, kind='serif'):
    """由真实字体边界生成略有笔势的开口圈，不覆盖字形。"""
    left, top, right, bottom = font(size,kind).getbbox(value,anchor='la')
    cx, cy = x+(left+right)/2, y+(top+bottom)/2
    rx, ry = (right-left)/2+11, (bottom-top)/2+18
    points=[]
    for index in range(181):
        a=math.radians(-19+354*index/180)
        wobble=1+.012*math.sin(3*a+.4)+.008*math.sin(7*a)
        points.append((cx+rx*math.cos(a)*wobble,cy+ry*math.sin(a)*wobble))
    return points

def hand_underline(x, y, value, size, kind='sans'):
    bottom=font(size,kind).getbbox(value,anchor='la')[3]
    length=width(value,size,kind)
    return [(x+length*i/60,y+bottom+8+2.2*math.sin(i/60*math.pi*1.5)) for i in range(61)]

def pen_stroke(image, points, progress=1):
    """按路径长度一笔画出；没有逐字轨迹和移动圆点。局部三倍采样平滑笔画。"""
    if progress<=0:
        return
    lengths=[math.dist(a,b) for a,b in zip(points,points[1:])]
    remaining=sum(lengths)*min(1,progress)
    visible=[points[0]]
    for a,b,length in zip(points,points[1:],lengths):
        if remaining>=length:
            visible.append(b)
            remaining-=length
        else:
            ratio=remaining/max(.001,length)
            visible.append((a[0]+(b[0]-a[0])*ratio,a[1]+(b[1]-a[1])*ratio))
            break
    left=math.floor(min(x for x,y in points))-5
    top=math.floor(min(y for x,y in points))-5
    right=math.ceil(max(x for x,y in points))+5
    bottom=math.ceil(max(y for x,y in points))+5
    if left<0 or right>RIGHT or top<140 or bottom>SAFE_BOTTOM:
        raise ValueError('手写强调进入平台遮挡区')
    overlay=Image.new('RGBA',((right-left)*3,(bottom-top)*3))
    draw=ImageDraw.Draw(overlay)
    draw.line([((x-left)*3,(y-top)*3) for x,y in visible],fill=COPPER,width=9,joint='curve')
    overlay=overlay.resize((right-left,bottom-top),Image.Resampling.LANCZOS)
    # 圈画靠近相邻文字时留下细小断口，保护真实印刷字形，不让强调笔画盖住阅读内容。
    printed=image.crop((left,top,right,bottom)).convert('L')
    dark=image.getpixel((0,0))==Image.new('RGB',(1,1),INK).getpixel((0,0))
    protected=printed.point(lambda value:255 if (value>180 if dark else value<80) else 0)
    protected=protected.filter(ImageFilter.MaxFilter(5))
    overlay.putalpha(ImageChops.multiply(overlay.getchannel('A'),ImageChops.invert(protected)))
    image.paste(overlay,(left,top),overlay)

