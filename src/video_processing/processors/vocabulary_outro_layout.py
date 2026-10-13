"""已确认的六维时空生词卡版式；文字按区域折行，不截断词条。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 固化 v4 视觉，三词分页和每页 3 秒的局部翻页 |
"""
from pathlib import Path
import math
import subprocess

from PIL import Image, ImageDraw, ImageFont
LOGO = Path(__file__).resolve().parents[3] / 'assets/brand/01_logos/concept_a.png'
PAGE_SECONDS = 3
PAGE_SIZE = 3

BG = '#0B1421'
PANEL = '#152537'
GOLD = '#DFC28B'
WHITE = '#F4F5F6'
MUTED = '#AFBECE'
TEAL = '#A4D4D0'


def font(role, size):
    base = Path('/System/Library/Fonts')
    paths = {'zh': base / 'Hiragino Sans GB.ttc', 'en': base / 'Supplemental/Georgia.ttf',
             'ipa': base / 'Supplemental/Arial.ttf'}
    return ImageFont.truetype(str(paths[role]), size)


def fit(text, role, width, size, minimum, max_lines=1):
    """按实际字宽测量，长句最多两行；超限明确失败，不隐藏内容。"""
    for current in range(size, minimum - 1, -1):
        face = font(role, current)
        tokens = list(text) if role == 'zh' else text.split(' ')
        separator = '' if role == 'zh' else ' '
        lines, line = [], ''
        for token in tokens:
            candidate = line + separator + token if line else token
            if face.getlength(candidate) <= width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = token
        if line:
            lines.append(line)
        if len(lines) <= max_lines and all(face.getlength(x) <= width for x in lines):
            return face, lines
    raise ValueError(f'生词卡文字超出版式容量: {text}')


def text_fit(draw, xy, text, role, width, size, minimum, fill, max_lines=1):
    face, lines = fit(text, role, width, size, minimum, max_lines)
    for index, line in enumerate(lines):
        draw.text((xy[0], xy[1] + index * (face.size + 3)), line, font=face, fill=fill)


def render_cards(items, title):
    cards = []
    pages = math.ceil(len(items) / PAGE_SIZE)
    logo = Image.open(LOGO).convert('RGB').resize((86, 86), Image.Resampling.LANCZOS)
    for page in range(pages):
        image = Image.new('RGB', (1080, 1920), BG)
        d = ImageDraw.Draw(image)
        image.paste(logo, (80, 207))
        d.text((190, 208), '六维时空号', font=font('zh', 35), fill=GOLD)
        d.text((190, 257), '不同的视角，看见更大的世界。', font=font('zh', 27), fill=MUTED)
        d.text((80, 331), '核心生词', font=font('zh', 72), fill=WHITE)
        text_fit(d, (82, 428), title, 'zh', 625, 33, 22, MUTED)
        d.line((738, 342, 738, 458), fill='#425064', width=2)
        text_fit(d, (779, 347), f'第 {page+1} 页', 'zh', 160, 39, 25, GOLD)
        text_fit(d, (781, 410), f'共 {pages} 页', 'zh', 160, 30, 22, MUTED)
        for j, item in enumerate(items[page*PAGE_SIZE:(page+1)*PAGE_SIZE]):
            y = 509+j*280
            d.rounded_rectangle((80, y, 936, y+258), radius=18, fill=PANEL)
            text_fit(d, (112, y+24), item['word'], 'en', 792, 60, 36, WHITE)
            text_fit(d, (113, y+100), item['phonetic'], 'ipa', 665, 33, 23, TEAL)
            stamp = item['timestamp']
            d.text((904-font('ipa', 28).getlength(stamp), y+106), stamp, font=font('ipa', 28), fill=MUTED)
            meaning_face, lines = fit(item['meaning_zh'], 'zh', 685, 42, 26)
            d.text((112, y+152), lines[0], font=meaning_face, fill=GOLD)
            text_fit(d, (132+meaning_face.getlength(lines[0]), y+161), item['pos'],
                     'ipa', 100, 26, 20, MUTED)
            d.line((112, y+215, 112, y+239), fill=TEAL, width=3)
            try:
                fit(item['excerpt'], 'ipa', 774, 32, 28)
                text_fit(d, (130, y+207), item['excerpt'], 'ipa', 774, 32, 28, MUTED)
            except ValueError:
                text_fit(d, (130, y+203), item['excerpt'], 'ipa', 774, 23, 20, MUTED, max_lines=2)
        d.rounded_rectangle((80, 1393, 936, 1508), radius=16, fill='#DFCA9F')
        d.line((508, 1416, 508, 1485), fill='#A08D69', width=2)
        for x, heading, caption in [(125, '单击暂停', '可截屏复习'), (558, '双击收藏', '随时回看')]:
            d.text((x, 1408), heading, font=font('zh', 39), fill='#172130')
            d.text((x+2, 1460), caption, font=font('zh', 26), fill='#46505D')
        cards.append(image)
    return cards


def frame_at(cards, frame, fps=24):
    page, local = divmod(frame, PAGE_SECONDS*fps)
    t = local/fps
    image = cards[page].copy()
    if page < len(cards)-1 and t >= 2.75:
        q = (t-2.75)/.25
        cut = int(856*(q*q*(3-2*q)))
        image.paste(cards[page+1].crop((80, 509, 80+cut, 1327)), (80, 509))
    d = ImageDraw.Draw(image)
    message = f'{max(1, math.ceil(PAGE_SECONDS-t))} 秒后' + (
        f'翻至第 {page+2} 页 →' if page < len(cards)-1 else '结束 · 暂停可细读')
    text_fit(d, (82, 1348), message, 'zh', 600, 25, 22, MUTED)
    d.rounded_rectangle((720, 1360, 934, 1365), radius=2, fill='#35465A')
    progress = (page+t/PAGE_SECONDS)/len(cards)
    d.rectangle((720, 1360, 720+int(214*progress), 1365), fill=GOLD)
    return image


def render_outro(cards, output):
    duration = len(cards)*PAGE_SECONDS
    command = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24',
               '-video_size', '1080x1920', '-framerate', '24', '-i', '-', '-f', 'lavfi',
               '-i', 'anullsrc=r=44100:cl=stereo', '-t', str(duration), '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-movflags', '+faststart', str(output)]
    with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
        try:
            for number in range(duration*24):
                process.stdin.write(frame_at(cards, number).tobytes())
            process.stdin.close()
            if process.wait(timeout=120):
                raise RuntimeError('生词片尾编码失败')
        except BaseException:
            process.kill()
            process.wait()
            raise
