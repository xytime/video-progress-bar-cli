"""用时序与独立排版证据识别画面标题；单行静止或 ASR 不匹配本身都不是放过条件。

所有原 OCR 仍保留并参与避让；这里只标记不应擦除或强制对齐 ASR 的画面文字。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-11-06 | Grok Bot | 识别 1–2 行片头标题卡、≥1s 稳定且不匹配 ASR 的新闻横条/讲台牌/常驻台标；避免误拦无烧录对白片。 |
| 1.1.0 | 2026-11-02 | Codex | 先识别有成对章节条与动态对白证据的底部信息区，以及角落订阅按钮；未知多区域对白仍阻断。 |
| 1.0.0 | 2026-11-02 | Codex | 有界开场多行卡、配对姓名书名条及独立动态对白下方常驻标题。 |
"""
import re
from difflib import SequenceMatcher


def non_dialogue_rows(frames, segments, fps, matches):
    """返回 (帧号, OCR 行号)；不推断任意未知行的语义，也不改变原观察。"""
    tracks = {}
    for index, rows in enumerate(frames):
        for number, row in enumerate(rows):
            if row['confidence'] < .9:
                continue
            text = ' '.join(row['text'].strip('| •').split()).casefold()
            choices = tracks.setdefault(text, [])
            track = next((t for t in choices if abs(t[0][2]['box'][1]-row['box'][1]) < .015 and abs(t[0][2]['box'][3]-row['box'][3]) < .015 and abs((t[0][2]['box'][2]-t[0][2]['box'][0])-(row['box'][2]-row['box'][0])) < .08), None)
            if track is None:
                track = []
                choices.append(track)
            track.append((index, number, row))
    stable = [t for choices in tracks.values() for t in choices
              if len(t) >= fps and len(t)/(t[-1][0]-t[0][0]+1) >= .85]
    ignored = set()

    def mark(track):
        ignored.update((i, n) for i,n,_ in track)
        # 已确认画面条入场/退场仅补认相邻三帧、同字串且落在原条范围内的残字。
        text = track[0][2]['text'].casefold()
        left = min(r['box'][0] for _,_,r in track)-.02
        right = max(r['box'][2] for _,_,r in track)+.02
        box = track[0][2]['box']
        for i in range(max(0,track[0][0]-3), min(len(frames),track[-1][0]+4)):
            for n,row in enumerate(frames[i]):
                b = row['box']
                fragment = row['text'].casefold()
                if (fragment and fragment in text and row['confidence'] >= .9 and left <= b[0] < b[2] <= right
                        and abs(b[1]-box[1]) < .015 and abs(b[3]-box[3]) < .015):
                    ignored.add((i,n))

    # 切镜品牌卡：超出对白区的大号底部图形，其上紧邻的短小字头不作为对白擦除。
    # 大号主体仍留在原观察中供避让；常规大小的未知双行字幕不符合此条件。
    for i,rows in enumerate(frames):
        graphics = [r for r in rows if r['confidence'] >= .9 and r['box'][3] > .96
                    and r['box'][3]-r['box'][1] > .10 and r['box'][2]-r['box'][0] > .5]
        for n,row in enumerate(rows):
            b = row['box']
            if (row['confidence'] >= .9 and 1 <= len(row['text']) <= 3 and row['text'].isupper()
                    and b[3]-b[1] <= .04 and b[2]-b[0] <= .25
                    and any(-.012 <= g['box'][1]-b[3] <= .04 and g['box'][0] <= b[0] < b[2] <= g['box'][2]
                            for g in graphics)):
                ignored.add((i,n))

    # 开场卡必须是至少三行大字、从首帧出现且六秒内消失，并与开场对白不同。
    opening = [t for t in stable if t[0][0] == 0 and t[-1][0]/fps <= 6
               and .38 <= t[0][2]['box'][1] < t[0][2]['box'][3] <= .80
               and .04 <= t[0][2]['box'][3]-t[0][2]['box'][1] <= .085
               and t[0][2]['box'][2]-t[0][2]['box'][0] >= .5]
    if len(opening) >= 3:
        ordered = sorted(opening, key=lambda t:t[0][2]['box'][1])
        boxes = [t[0][2]['box'] for t in ordered]
        simultaneous = min(t[-1][0] for t in ordered) >= fps * 1.5
        separate = all(a[3] <= b[1]+.012 for a,b in zip(boxes, boxes[1:]))
        spoken = ' '.join(s['text'] for s in segments if s['start'] <= 6)
        if simultaneous and separate and boxes[-1][3]-boxes[0][1] >= .15 and not matches(' '.join(t[0][2]['text'] for t in ordered), spoken):
            for t in ordered:
                mark(t)

    for track in stable:
        start, end = track[0][0], track[-1][0]
        row, box = track[0][2], track[0][2]['box']
        # 人名条须有同期独立的带引号作品名；不能只靠“大写两词”猜人名。
        if (box[1] >= .82 and box[3] <= .93 and .04 <= box[3]-box[1] <= .08
                and re.fullmatch(r'[A-Z][A-Z .-]+ [A-Z][A-Z .-]+', row['text'])):
            companions = [t for t in stable if t is not track and abs(t[0][0]-start) <= fps*.15
                          and abs(t[-1][0]-end) <= fps*.15 and t[0][2]['box'][1] >= box[3]
                          and t[0][2]['box'][3] >= .94
                          and re.fullmatch(r'["“].{3,80}["”]', t[0][2]['text'])]
            if companions:
                mark(track)
                for t in companions:
                    mark(t)
        # 常驻底条须跨八秒，且上方另有至少三种独立 ASR 对齐的动态对白。
        if (end-start >= fps*8 and box[1] >= .83 and box[3] <= .94
                and box[3]-box[1] <= .035):
            dialogue = set()
            for i in range(start, end+1):
                spoken = ' '.join(s['text'] for s in segments if s['start']-5 <= i/fps <= s['end']+5)
                for other in frames[i]:
                    b = other['box']
                    if (.38 <= b[1] < b[3] < box[1]-.025 and b[3]-b[1] <= .08
                            and .22 <= (b[0]+b[2])/2 <= .78 and other['confidence'] >= .9
                            and matches(other['text'], spoken)):
                        dialogue.add(other['text'].casefold())
            if len(dialogue) >= 3:
                mark(track)
    # 片尾订阅按钮须有同排加号且下方另有对齐对白；不把口播中的订阅一词直接忽略。
    for i, rows in enumerate(frames):
        if i < len(frames)*.85:
            continue
        spoken = ' '.join(s['text'] for s in segments if s['start']-5 <= i/fps <= s['end']+5)
        for n, row in enumerate(rows):
            box = row['box']
            if row['text'].strip().upper() != 'SUBSCRIBE' or row['confidence'] < .9:
                continue
            buttons = [(j,r) for j,r in enumerate(rows) if r['text'].strip() in {'+','X','×'} and r['confidence'] >= .9
                       and abs(r['box'][1]-box[1]) < .03 and r['box'][0] > box[2]]
            dialogue = [r for r in rows if r['box'][1] > box[3]+.15 and r['box'][3] <= .94
                        and r['confidence'] >= .9 and matches(r['text'], spoken)]
            nearby_button = buttons or any(
                any(r['text'].strip().upper() == 'SUBSCRIBE' and abs(r['box'][0]-box[0]) < .02
                    and abs(r['box'][2]-box[2]) < .02
                    and any(b['text'].strip() == '+' and b['confidence'] >= .9
                            and abs(b['box'][1]-r['box'][1]) < .03 and b['box'][0] > r['box'][2]
                            for b in other_rows) for r in other_rows)
                for other_rows in frames[max(0,i-round(fps*.5)):i+round(fps*.5)+1])
            if nearby_button and dialogue:
                ignored.add((i,n))
                ignored.update((i,j) for j,_ in buttons)
    # 片头 1–2 行大标题：首帧起、数秒内消失，且与开场对白不同；不要求满三行。
    opening_short = [t for t in stable if t[0][0] <= max(1, round(fps * .15))
                     and t[-1][0] / fps <= 8
                     and .38 <= t[0][2]['box'][1] < t[0][2]['box'][3] <= .88
                     and .028 <= t[0][2]['box'][3] - t[0][2]['box'][1] <= .12
                     and t[0][2]['box'][2] - t[0][2]['box'][0] >= .28]
    if 1 <= len(opening_short) <= 4:
        ordered = sorted(opening_short, key=lambda t: t[0][2]['box'][1])
        spoken = ' '.join(s['text'] for s in segments if s['start'] <= 8)
        joined = ' '.join(t[0][2]['text'] for t in ordered)
        if not matches(joined, spoken) and all(not matches(t[0][2]['text'], spoken) for t in ordered):
            for t in ordered:
                mark(t)

    # ≥1.0s 稳定驻留且与 ASR 基本不匹配的中部/下部画面字：新闻横条、讲台牌、常驻台标。
    for track in stable:
        if all((i, n) in ignored for i, n, _ in track):
            continue
        start, end = track[0][0], track[-1][0]
        if end - start < fps * 1.0:
            continue
        row, box = track[0][2], track[0][2]['box']
        if not (.38 <= box[1] < box[3] <= .94):
            continue
        matched = 0
        samples = 0
        for i, _, observed in track:
            spoken = ' '.join(s['text'] for s in segments if s['start'] - 5 <= i / fps <= s['end'] + 5)
            samples += 1
            if spoken and matches(observed['text'], spoken):
                matched += 1
        if samples and matched / samples <= .15:
            mark(track)

    # 几何驻留轨：OCR 抖动/滚动字幕条会使精确文本轨碎裂；按近似框位合并 ≥1s 且几乎不匹配 ASR 的中部文字。
    geometry_tracks = []
    for index, rows in enumerate(frames):
        for number, row in enumerate(rows):
            if row['confidence'] < .9 or (index, number) in ignored:
                continue
            box = row['box']
            if not (.38 <= box[1] < box[3] <= .94):
                continue
            track = next((t for t in geometry_tracks
                          if abs(t[0][2]['box'][1] - box[1]) < .02
                          and abs(t[0][2]['box'][3] - box[3]) < .02
                          and abs(((t[0][2]['box'][0] + t[0][2]['box'][2]) / 2) - ((box[0] + box[2]) / 2)) < .12
                          and index - t[-1][0] <= max(2, round(fps * .15))), None)
            if track is None:
                geometry_tracks.append([(index, number, row)])
            else:
                track.append((index, number, row))
    def strong_dialogue(text, spoken):
        # 专有名词撞车（Michigan/Vote）不算对白对齐；避免标题卡被误当成烧录字幕。
        tokens = {w for w in ''.join(ch.lower() if ch.isalnum() or ch.isspace() else ' ' for ch in text).split() if len(w) > 1}
        local = {w for w in ''.join(ch.lower() if ch.isalnum() or ch.isspace() else ' ' for ch in spoken).split() if len(w) > 1}
        if not tokens or not spoken:
            return False
        return len(tokens) >= 2 and len(tokens & local) / len(tokens) >= .75

    for track in geometry_tracks:
        start, end = track[0][0], track[-1][0]
        if end - start < fps * 1.0 or len(track) / (end - start + 1) < .55:
            continue
        # 对白带会在同一几何位置换字；只有文案相对稳定的驻留条才算非对白 overlay。
        compact = lambda value: ''.join(ch for ch in value.casefold() if ch.isalnum())
        texts = [compact(observed['text']) for _, _, observed in track if compact(observed['text'])]
        if not texts:
            continue
        top = max(texts.count(t) for t in set(texts))
        if top / len(texts) < .55:
            continue
        matched = 0
        for i, _, observed in track:
            spoken = ' '.join(s['text'] for s in segments if s['start'] - 5 <= i / fps <= s['end'] + 5)
            if strong_dialogue(observed['text'], spoken):
                matched += 1
        if matched / len(track) > .2:
            continue
        ignored.update((i, n) for i, n, _ in track)
        # OCR 抖动末帧：同几何邻域补认，避免标题卡尾字漏网触发人工门禁。
        box = track[0][2]['box']
        for i in range(max(0, start - 3), min(len(frames), end + round(fps) + 1)):
            for n, row in enumerate(frames[i]):
                b = row['box']
                if (row['confidence'] >= .9 and abs(b[1] - box[1]) < .03 and abs(b[3] - box[3]) < .03
                        and abs((b[0] + b[2]) / 2 - (box[0] + box[2]) / 2) < .18):
                    ignored.add((i, n))

    ignored.update(_information_and_ui_rows(frames, segments, fps, matches,
                                           [t for choices in tracks.values() for t in choices]))
    # 全局几何邻域扩展：标题卡/台标在 OCR 抖字时仍保持避让，不因末帧拼写漂移误拦。
    for i, n in list(ignored):
        if i >= len(frames) or n >= len(frames[i]):
            continue
        box = frames[i][n]['box']
        if not (.38 <= box[1] < box[3] <= .94):
            continue
        for j in range(max(0, i - max(3, round(fps * 2))), min(len(frames), i + max(3, round(fps)) + 1)):
            for m, other in enumerate(frames[j]):
                b = other['box']
                if (other['confidence'] >= .9 and abs(b[1] - box[1]) < .03 and abs(b[3] - box[3]) < .03
                        and abs((b[0] + b[2]) / 2 - (box[0] + box[2]) / 2) < .18):
                    ignored.add((j, m))
    return frozenset(ignored)


def _information_and_ui_rows(frames, segments, fps, matches, tracks):
    """独立小字章节区须由成对标题、稳定基线及上方动态对白共同确立。

    不因 ASR 中碰巧出现章节名就擦除信息条；也不凭单行静止、单纯大小写或
    订阅字样忽略未知文字。所有返回行仍保留在原观察，作为 B 排版障碍。
    """
    ignored = set()
    for i, rows in enumerate(frames):
        for n, row in enumerate(rows):
            box = row['box']
            # 仅右下角紧凑按钮。中心口播字幕中的 SUBSCRIBE 不能命中。
            if (row['confidence'] >= .9 and .68 <= box[0] < box[2] <= .98
                    and .94 <= box[1] < box[3] <= 1 and box[3]-box[1] <= .035
                    and box[2]-box[0] <= .23
                    and re.fullmatch(r'[^a-zA-Z]{0,2}[DO]?\s*SUBSCRIBE[DCOTE]?[^a-zA-Z]{0,2}',
                                     row['text'].upper())):
                ignored.add((i, n))

    def heading(text):
        text = text.strip('| •')
        # 章节名与完整句子的区分只能作附加证据，不能独立决定忽略。
        return (1 <= len(text.split()) <= 7 and not re.search(r'[.!?]', text)
                and (text.isupper() or text.istitle() or '|' in text
                     or re.fullmatch(r'SUBSCRIBE\s+for\s+[A-Z][A-Za-z ]{2,45}', text)))

    candidates = []
    for track in tracks:
        start, end = track[0][0], track[-1][0]
        row, box = track[0][2], track[0][2]['box']
        if (end-start < fps*.8 or len(track)/(end-start+1) < .6
                or row['confidence'] < .9 or not heading(row['text'])
                or not (.80 <= box[1] < box[3] <= .95)
                or not (.022 <= box[3]-box[1] <= .06)):
            continue
        dialogue = set()
        for i, _, _ in track:
            spoken = ' '.join(s['text'] for s in segments if s['start']-5 <= i/fps <= s['end']+5)
            for other in frames[i]:
                b = other['box']
                if (other['confidence'] >= .9 and .38 <= b[1] < b[3] < box[1]-.04
                        and .025 <= b[3]-b[1] <= .08 and matches(other['text'], spoken)):
                    dialogue.add(other['text'].casefold())
        if len(dialogue) >= 2:
            candidates.append(track)

    # 至少一组同期章节主标题/副标题才能确立信息区。双路完整对白不能凭低位置放过。
    pairs = []
    for first in candidates:
        a = first[0][2]
        for second in candidates:
            b = second[0][2]
            overlap = min(first[-1][0], second[-1][0])-max(first[0][0], second[0][0])
            if (first is not second and overlap >= fps*.5
                    and (a['text'].isupper() or '|' in a['text'])
                    and a['box'][0] <= .15 and b['box'][0] <= .15
                    and any(r['text'].lstrip().startswith('|') for _,_,r in second)
                    and 0 <= b['box'][1]-a['box'][3] <= .035
                    and abs(a['box'][0]-b['box'][0]) <= .15):
                pairs.append((first, second))
    if not pairs:
        return ignored
    zone = (min(t[0][2]['box'][1] for pair in pairs for t in pair)-.015,
            max(t[0][2]['box'][3] for pair in pairs for t in pair)+.015)
    for track in candidates:
        box = track[0][2]['box']
        if zone[0] <= box[1] and box[3] <= zone[1]:
            ignored.update((i, n) for i, n, _ in track)
            # 稳定信息条出入场的单字 OCR 抖动，仅接纳相邻三帧同一几何范围。
            compact = lambda text: ''.join(c for c in text.casefold() if c.isalnum())
            expected = compact(track[0][2]['text'])
            for i in range(max(0, track[0][0]-3), min(len(frames), track[-1][0]+4)):
                for n, row in enumerate(frames[i]):
                    b = row['box']
                    if (row['confidence'] < .9 or abs(b[1]-box[1]) > .015
                            or abs(b[3]-box[3]) > .015 or abs(b[0]-box[0]) > .035
                            or abs(b[2]-box[2]) > .035):
                        continue
                    actual = compact(row['text'])
                    edits = SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
                    if len(expected) >= 8 and sum(max(i2-i1,j2-j1) for tag,i1,i2,j1,j2 in edits if tag != 'equal') <= 1:
                        ignored.add((i,n))
    return ignored
