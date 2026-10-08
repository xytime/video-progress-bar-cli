"""mobile-2 通用完整母带：Pillow 绘制 + 单个受限 FFmpeg 编码进程。

字幕指读复用本地词时码；二创仅圈画。RGBA 画布中的透明视频窗由同一
FFmpeg 读取原片填入，无全片 rawvideo 临时文件，也无需两个 FFmpeg 并行。
# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.1 | 2026-10-09 | Codex | 整段字幕共用真实 ASR 锚点，避免事件边界漏词 |
| 1.0.0 | 2026-10-09 | Codex | 固化已批准视觉、完整原片与六要点，按真实字宽分页 |
"""
from __future__ import annotations
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import pysubs2
from PIL import Image, ImageDraw, ImageOps
from video_processing.processors import mobile_editorial_layout as m
from video_processing.processors.insight_editorial import wrap
from video_processing.utils.video_metadata import resolve_ffmpeg_cmd
from config.settings import settings


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def align_audio(processor, source, output):
    """缓存严格绑定音轨字节与本地模型；不联网下载模型。"""
    import whisper
    model_path = Path.home()/'.cache/whisper/small.pt'
    if not model_path.is_file():
        raise ValueError('指读需要已安装的本地 Whisper small 模型')
    fingerprint = {'audio':digest(source),'model':digest(model_path),'recipe':'words-small-1'}
    cache = settings.default_output_dir / 'wallstreet_alignment_cache'
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / (hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()+'.json')
    if output.is_file():
        saved = json.loads(output.read_text())
        if saved.get('fingerprint') == fingerprint:
            return saved['words']
    wav = output.with_suffix('.wav')
    processor.run(['-i',str(source),'-vn','-ar','16000','-ac','1',str(wav)])
    model = whisper.load_model(str(model_path),device='cpu')
    try:
        result = model.transcribe(str(wav),word_timestamps=True,fp16=False,verbose=False)
        words = [word for segment in result['segments'] for word in segment.get('words',[])]
        if not words:
            raise ValueError('缺少真实词时码')
        temporary = output.with_suffix('.tmp.json')
        temporary.write_text(json.dumps({'fingerprint':fingerprint,'words':words},ensure_ascii=False))
        temporary.replace(output)
        return words
    finally:
        del model
        wav.unlink(missing_ok=True)


def base(dark=False):
    image = Image.new('RGB',(m.W,m.H),m.INK if dark else m.PAPER)
    m.brand(image,dark)
    return image


def draw_block(image,value,xy,size,*,serif=False,color=m.INK,bottom=m.SAFE_BOTTOM):
    lines = wrap(value,size,m.RIGHT-xy[0],serif)
    step = round(size*1.4)
    positions = []
    draw = ImageDraw.Draw(image)
    for i,line in enumerate(lines):
        x,y = xy[0],xy[1]+i*step
        bbox = m.font(size,'serif' if serif else 'sans').getbbox(line,anchor='la')
        if y+bbox[3] > bottom:
            raise ValueError('正文超过手机可读区域，不能截字')
        m.text(draw,line,(x,y),size,color,'serif' if serif else 'sans')
        positions.append((line,x,y))
    return positions


def hand_mark(image,lines,term,size,*,serif=False,progress=1):
    kind = 'serif' if serif else 'sans'
    for line,x,y in lines:
        if term in line:
            start = x+m.width(line[:line.index(term)],size,kind)
            m.pen_stroke(image,m.hand_circle(start,y,term,size,kind),progress)
            return True
    return False


def pick_term(text,keywords):
    return next((term for term in keywords if term in text),None)


def narration_pages(text,words,size=39):
    """整句分页，仅切换文字页，无逐字指读；依据真实 ASR 边界换页。"""
    lines = wrap(text,size,m.RIGHT-m.LEFT)
    chunks = [''.join(lines[i:i+2]) for i in range(0,len(lines),2)]
    all_positions = [{'char':c,'x':0,'width':1,'y':0,'line':0} for c in text if c.isalnum()]
    aligned = m.align_positions(all_positions,words)
    result,offset = [],0
    for chunk in chunks:
        count = sum(c.isalnum() for c in chunk)
        part = aligned[offset:offset+count]
        if not part:
            raise ValueError('口播分页缺少时码')
        result.append({'text':chunk,'start':0 if not result else part[0]['start'],'end':part[-1]['end']})
        offset += count
    return result


def caption_pages(ass_path,words,duration):
    subs = pysubs2.load(str(ass_path), format_='ass')
    glossary = {}
    for event in subs:
        if event.style == 'GlossaryCard':
            plain = re.sub(r'^词汇\s*','',event.plaintext)
            glossary[(event.start,event.end)] = re.findall(r"([A-Za-z][A-Za-z .'-]*?)\s*·\s*([\u3400-\u9fffA-Za-z]+)",plain)
    entries = []
    for event in subs:
        if event.is_comment or event.style == 'GlossaryCard':
            continue
        lines = [s.strip() for s in event.plaintext.splitlines() if s.strip()]
        split = next((i for i,line in enumerate(lines) if re.search(r'[\u3400-\u9fff]',line)),None)
        if split is None or split == 0 or event.start < 0 or event.end > (duration+.12)*1000:
            raise ValueError('字幕缺少双语或不属于该完整原片')
        en,zh = ' '.join(lines[:split]),''.join(lines[split:])
        vocab = glossary.get((event.start,event.end),[])
        entries.append((event,en,zh,vocab))
    # ASS 切句与 ASR 词边界不同；全片顺序匹配后按字符偏移分配，
    # 保留真实语音锚点与全局覆盖门槛，不能靠放宽事件时间窗猜测词序。
    all_pos = [{'char':c,'x':0,'y':0,'width':1,'line':0}
               for _,en,_,_ in entries for c in en if c.isalnum()]
    aligned_all = m.align_positions(all_pos,words)
    pages,offset = [],0
    for event,en,zh,vocab in entries:
        size = sum(c.isalnum() for c in en)
        full = aligned_all[offset:offset+size]
        offset += size
        # 释义与短语作为同一 token，不拆成独立生词列表。
        terms = dict(vocab)
        pattern = '('+'|'.join(re.escape(t) for t in sorted(terms,key=len,reverse=True))+')' if terms else None
        tokens = []
        for part in re.split(pattern,en) if pattern else [en]:
            tokens += [part] if part in terms else re.findall(r'\s+|\S+',part)
        rows,line,length = [],[],0
        for token in tokens:
            size = m.width(token,35,'en')+(m.width('（'+terms[token]+'）',26) if token in terms else 0)
            if size > m.RIGHT-m.LEFT:
                raise ValueError('完整短语及释义无法容纳')
            if line and length+size > m.RIGHT-m.LEFT:
                rows.append(line);line=[];length=0
            if not line and token.isspace():
                continue
            line.append(token);length+=size
        if line:
            rows.append(line)
        atoms = sorted(set(terms.values()), key=len, reverse=True)
        zh_tokens = re.findall('|'.join(re.escape(t) for t in atoms)+r'|.' if atoms else r'.',zh)
        zh_rows, current = [], ''
        for token in zh_tokens:
            if m.width(token,43) > m.RIGHT-m.LEFT:
                raise ValueError('中文重点短语超过可读宽度')
            if current and m.width(current+token,43) > m.RIGHT-m.LEFT:
                zh_rows.append(current); current = ''
            current += token
        if current:
            zh_rows.append(current)
        count = max(math.ceil(len(rows)/3),math.ceil(len(zh_rows)/2))
        for i in range(count):
            selected = rows[len(rows)*i//count:len(rows)*(i+1)//count]
            selected_zh = zh_rows[len(zh_rows)*i//count:len(zh_rows)*(i+1)//count]
            if not selected or not selected_zh:
                raise ValueError('字幕太密，不能删除任一语言')
            text = ''.join(token for row in selected for token in row)
            pos = []
            for j,row in enumerate(selected):
                x,y = m.LEFT,1077+j*48
                for token in row:
                    for char in token:
                        if char.isalnum():
                            pos.append({'char':char,'x':x,'y':y+44,'width':m.width(char,35,'en'),'line':y})
                        x+=m.width(char,35,'en')
                    if token in terms:
                        x+=m.width('（'+terms[token]+'）',26)
            preceding = sum(c.isalnum() for row in rows[:len(rows)*i//count] for token in row for c in token)
            timing = full[preceding:preceding+len(pos)]
            if len(timing) != len(pos):
                raise ValueError('指读分页无法完整对齐')
            aligned = [dict(p,start=t['start'],end=t['end']) for p,t in zip(pos,timing)]
            start = event.start/1000 if i == 0 else timing[0]['start']
            end = event.end/1000 if i == count-1 else full[preceding+len(pos)]['start']
            if end-start < .7:
                raise ValueError('字幕页阅读时间不足')
            pages.append({'start':start,'end':end,'rows':selected,'zh':'\n'.join(selected_zh),'terms':terms,'positions':aligned})
    if not pages:
        raise ValueError('没有双语字幕')
    return pages


def draw_caption(image,page):
    draw = ImageDraw.Draw(image)
    for j,row in enumerate(page['rows']):
        x,y = m.LEFT,1077+j*48
        for token in row:
            is_term = token in page['terms']
            m.text(draw,token,(x,y),35,m.COPPER if is_term else m.INK,'en')
            x+=m.width(token,35,'en')
            if is_term:
                meaning = '（'+page['terms'][token]+'）'
                m.text(draw,meaning,(x,y+12),26,m.COPPER)
                x+=m.width(meaning,26)
    # 中文高亮释义按完整短语原子折行，再在精确字符位置重绘铜色。
    positions = m.chinese_layout(image,page['zh'],(m.LEFT,1230),43,step=59,atoms=page['terms'].values())
    for term in page['terms'].values():
        for match in re.finditer(re.escape(term),page['zh']):
            offset = sum(c.isalnum() for c in page['zh'][:match.start()])
            for pos in positions[offset:offset+sum(c.isalnum() for c in term)]:
                m.text(draw,pos['char'],(pos['x'],pos['line']),43,m.COPPER)


def encode_frames(processor,frames,count,output,source,*,body=False):
    raw = ['-f','rawvideo','-pix_fmt','rgba','-s',f'{m.W}x{m.H}','-r','30','-i','pipe:0']
    args = [resolve_ffmpeg_cmd(),'-nostdin','-v','error','-y','-i',str(source),*raw]
    if body:
        filters = (f'[0:v]setpts=PTS-STARTPTS,scale=1080:{m.VIDEO_H}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
            f'pad=1080:{m.VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=0xF2EEE5,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=0.1[raw];'
            f'[raw]pad=1080:1920:0:{m.VIDEO_Y}:color=0xF2EEE5[back];[back][1:v]overlay=0:0:shortest=1[v]')
        args += ['-filter_complex',filters,'-map','[v]','-map','0:a']
    else:
        args += ['-map','1:v','-map','0:a']
    args += ['-af','aresample=44100,aformat=channel_layouts=stereo,apad','-t',str(count/30),*processor.codecs(),str(output)]
    # Popen 仍由项目共享 FFmpeg 名额保护；唯一进程负责原片读取和编码。
    with output.with_suffix('.encode.log').open('w') as log:
        process = subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
        try:
            for image in frames:
                process.stdin.write(image.convert('RGBA').tobytes())
            process.stdin.close()
            if process.wait(timeout=900) != 0:
                raise RuntimeError('母带编码失败，见 encode.log')
        except BaseException:
            process.kill();process.wait()
            raise


def render_segments(processor,script,original,original_ass,work,body_duration,voice,get_duration):
    keys = [p.keyword for card in script.cards for p in card.points]
    poster = work/'poster.png'
    processor.run(['-ss',str(min(1,body_duration/2)),'-i',str(original),'-frames:v','1','-vf','scale=1080:608:force_original_aspect_ratio=decrease,pad=1080:608:(ow-iw)/2:(oh-ih)/2',str(poster)])
    segments = [work/f'seg{i}.mp4' for i in range(3)]
    lengths = []
    manifest = []
    for index,narration in enumerate((script.hook.narration,script.outro.tts_narration)):
        audio = work/f'voice-{index}.wav'
        processor.tts.generate_audio(narration,audio,voice=voice)
        words = align_audio(processor,audio,work/f'voice-{index}-words.json')
        seconds = math.ceil((get_duration(audio)+.45)*30)/30
        lengths.append(seconds)
        if index == 0:
            image = base(True)
            image.paste(Image.open(poster).convert('RGB'),(0,280))
            shade = Image.new('RGBA',(m.W,m.H))
            d = ImageDraw.Draw(shade)
            for y in range(660,1050):
                d.line((0,y,m.W,y),fill=(25,28,28,round(255*min(1,(y-660)/240))))
            image = Image.alpha_composite(image.convert('RGBA'),shade).convert('RGB')
            m.brand(image,True)
            m.text(ImageDraw.Draw(image),'本期观察',(m.LEFT,915),30,m.COPPER)
            title_lines = draw_block(image,script.hook.title,(m.LEFT,978),84,serif=True,color=m.PAPER,bottom=1310)
            pages = narration_pages(narration,words)
        else:
            image = base()
            m.text(ImageDraw.Draw(image),'把判断留在评论区',(m.LEFT,338),31,m.COPPER)
            title_lines = draw_block(image,script.outro.reflection_question,(m.LEFT,418),65,serif=True,bottom=750)
            for i,option in enumerate(script.outro.poll_options):
                m.text(ImageDraw.Draw(image),f'{i+1:02d}',(m.LEFT,800+i*91),42,m.COPPER,'serif')
                draw_block(image,option,(m.LEFT+120,800+i*91),45,bottom=1100)
            draw_block(image,script.outro.comment_invitation,(m.LEFT,1110),39,color=m.COPPER,bottom=1170)
            draw_block(image,script.outro.philosophical_quote,(m.LEFT,1185),25,bottom=1250)
            d = ImageDraw.Draw(image)
            d.line((m.LEFT,1253,m.RIGHT,1253),fill='#C8B9A7',width=1)
            d.rectangle((0,1270,m.W,1476),fill='#E8E2D8')
            code = ImageOps.contain(Image.open(m.QR).convert('RGB'),(178,178))
            d.rectangle((m.LEFT,1284,m.LEFT+192,1466),fill='white')
            image.paste(code,(m.LEFT+7,1286))
            m.text(d,'六维时空号',(m.LEFT+250,1322),39,m.INK,'serif')
            m.text(d,'持续观察，',(m.LEFT+250,1384),29)
            m.text(d,'保持独立判断。',(m.LEFT+250,1427),29)
            pages = []
        term = pick_term(''.join(l[0] for l in title_lines),keys)
        # 仅口播实际包含该词时按词时码画圈，其余静态强调。
        term_start = next((w['start'] for w in words if term and term in w['word']),None)
        def frames(image=image,pages=pages,title_lines=title_lines,term=term,term_start=term_start,index=index,seconds=seconds):
            for n in range(round(seconds*30)):
                t = n/30
                frame = image.copy()
                if pages:
                    page = next((p for p in reversed(pages) if p['start']<=t),pages[0])
                    draw_block(frame,page['text'],(m.LEFT,1361),39,color=m.PAPER,bottom=1480)
                if term:
                    hand_mark(frame,title_lines,term,84 if index == 0 else 65,serif=True,
                              progress=1 if term_start is None else (t-term_start)/.55)
                if n == round(min(seconds-1,3)*30):
                    frame.save(work/('intro.png' if index == 0 else 'outro.png'))
                yield frame
        encode_frames(processor,frames(),round(seconds*30),segments[index*2],audio)
    core_duration = math.ceil(body_duration*30)/30
    words = align_audio(processor,original,work/'body-words.json')
    captions = caption_pages(original_ass,words,body_duration)
    for card in script.cards:
        for i,point in enumerate(card.points):
            t0 = card.start_sec+(card.end_sec-card.start_sec)*i/3
            t1 = card.start_sec+(card.end_sec-card.start_sec)*(i+1)/3
            manifest.append({'card_id':card.card_id,'point':i+1,'start':t0,'end':t1,'keyword':point.keyword,
                             'explanation':point.explanation,'title':card.title,'badge':card.badge})
    background = base()
    @lru_cache(maxsize=8)
    def caption_base(index):
        image = background.copy()
        if index is not None:
            draw_caption(image,captions[index])
        return image
    def body_frames():
        cursor = 0
        for n in range(round(core_duration*30)):
            t = n/30
            while cursor < len(captions)-1 and captions[cursor]['end']<=t:
                cursor+=1
            page = captions[cursor] if captions[cursor]['start']<=t<captions[cursor]['end'] else None
            frame = caption_base(cursor if page else None).copy()
            point = next((p for p in manifest if p['start']<=t<p['end']),None)
            draw_block(frame,point['title'] if point else script.headline,(m.LEFT,306),46,serif=True,bottom=435)
            if point:
                d = ImageDraw.Draw(frame)
                d.line((m.LEFT,1365,m.RIGHT,1365),fill='#CDBBA6',width=1)
                m.text(d,point['badge']+'  /  '+str(point['point']).zfill(2),(m.LEFT,1383),25,m.COPPER)
                lines = draw_block(frame,point['keyword'],(m.LEFT+310,1379),31,serif=True,bottom=1428)
                hand_mark(frame,lines,point['keyword'],31,serif=True,progress=(t-point['start'])/.55)
                explanations = wrap(point['explanation'],31,m.RIGHT-m.LEFT)
                j = min(len(explanations)-1,int((t-point['start'])/(point['end']-point['start'])*len(explanations)))
                draw_block(frame,explanations[j],(m.LEFT,1434),31,bottom=1480)
            if page:
                m.pointer(frame,page['positions'],t)
            frame = frame.convert('RGBA')
            d = ImageDraw.Draw(frame)
            d.rectangle((0,m.VIDEO_Y,m.W,m.VIDEO_Y+m.VIDEO_H-1),fill=(0,0,0,0))
            d.line((0,m.VIDEO_Y,m.W-1,m.VIDEO_Y),fill='#D7C9B7',width=1)
            d.line((0,m.VIDEO_Y,round((m.W-1)*min(1,t/body_duration)),m.VIDEO_Y),fill=m.COPPER,width=1)
            if n == 30:
                frame.save(work/'body-overlay.png')
            yield frame
    encode_frames(processor,body_frames(),round(core_duration*30),segments[1],original,body=True)
    return segments,lengths,core_duration,manifest
