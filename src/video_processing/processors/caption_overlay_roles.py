"""用时序与独立排版证据识别画面标题；单行静止或 ASR 不匹配本身都不是放过条件。

所有原 OCR 仍保留并参与避让；这里只标记不应擦除或强制对齐 ASR 的画面文字。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-02 | Codex | 有界开场多行卡、配对姓名书名条及独立动态对白下方常驻标题。 |
"""
import re


def non_dialogue_rows(frames, segments, fps, matches):
    """返回 (帧号, OCR 行号)；不推断任意未知行的语义，也不改变原观察。"""
    tracks = {}
    for index, rows in enumerate(frames):
        for number, row in enumerate(rows):
            if row['confidence'] < .9:
                continue
            text = ' '.join(row['text'].split()).casefold()
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
    return frozenset(ignored)
