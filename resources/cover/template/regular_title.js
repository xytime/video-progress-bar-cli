/* HTMLRenderer → 本地排版；不依赖发布、配置或数据库。2026-10-20 / Codex。 */
() => {
    const heading = document.querySelector('.main-title');
    const group = document.querySelector('.content-area');
    const title = heading.textContent.trim();
    if (!title || title.length > 160) throw new Error('封面主标题为空或过长，需人工复核');

    // 使用浏览器本地词界；保护会被通用分词器拆开的常见完整术语。
    const protectedTerms = ['人工智能', '公共健康', '半导体', '美联储', '供应链', '量子计算', '重塑', '教会'];
    const segments = [...new Intl.Segmenter('zh-CN', {granularity: 'word'}).segment(title)];
    const boundaries = segments.slice(1).map(item => item.index).filter(index => {
        if (/^[，。！？、：；,.!?;:）】》”’]/u.test(title.slice(index))) return false;
        if (/[（【《“‘]$/u.test(title.slice(0, index))) return false;
        return !protectedTerms.some(term => {
            let start = title.indexOf(term);
            while (start >= 0) {
                if (start < index && index < start + term.length) return true;
                start = title.indexOf(term, start + 1);
            }
            return false;
        });
    });
    const context = document.createElement('canvas').getContext('2d');
    // 逐行底板左侧突出 20px，右侧仍在内容安全区内。
    const maxTextWidth = group.clientWidth - 20;
    let chosen = null;
    for (const size of [144, 136, 128]) {
        context.font = `900 ${size}px ${getComputedStyle(group).fontFamily}`;
        const width = text => context.measureText(text).width;
        if (width(title) <= maxTextWidth) {
            chosen = {size, lines: [title]};
            break;
        }
        let best = null;
        for (const index of boundaries) {
            const lines = [title.slice(0, index).trimEnd(), title.slice(index).trimStart()];
            if (lines.some(line => [...line].length < 2 || width(line) > maxTextWidth)) continue;
            const score = Math.abs(width(lines[0]) - width(lines[1]))
                + (/^[的是了]/u.test(lines[1]) ? size * 3 : 0)
                + (/(如何|怎么|是否|正在|即将)$/u.test(lines[0]) ? size * 3 : 0);
            if (!best || score < best.score) best = {size, lines, score};
        }
        if (best) { chosen = best; break; }
    }
    if (!chosen) throw new Error('封面主标题无法在 128px 以上完整排入两行，需人工复核');
    heading.replaceChildren(...chosen.lines.map(text => {
        const line = document.createElement('span');
        line.className = 'title-line';
        line.textContent = text;
        return line;
    }));
    heading.style.fontSize = `${chosen.size}px`;

    const subtitle = document.querySelector('.sub-title');
    if (subtitle) {
        const style = getComputedStyle(subtitle);
        const innerHeight = subtitle.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
        if (innerHeight > parseFloat(style.lineHeight) * 2 + 1) {
            throw new Error('封面副标题超过两行，需人工复核');
        }
    }
    const elements = [...document.querySelectorAll('.badge-capsule,.title-line,.sub-title')]
        .filter(el => getComputedStyle(el).display !== 'none');
    const bounds = elements.map(el => {
        const r = el.getBoundingClientRect();
        if (r.left < innerWidth * .05 || r.right > innerWidth * .93 + 1
            || r.top < innerHeight * .12 - 1 || r.bottom > innerHeight * .88 + 1
            || el.scrollWidth > el.clientWidth + 1) {
            throw new Error('封面文字超出安全区，需人工复核');
        }
        return {text: el.textContent, x: r.x, y: r.y, width: r.width, height: r.height};
    });
    const badge = document.querySelector('.badge-capsule');
    if (badge && getComputedStyle(badge).display !== 'none'
        && badge.getBoundingClientRect().bottom + 24 > group.getBoundingClientRect().top) {
        throw new Error('封面类别与标题发生碰撞，需人工复核');
    }
    return {style: 'opaque_title_strips_v1', font_size: chosen.size, lines: chosen.lines,
        headline_position: 'lower_left', bounds};
}
