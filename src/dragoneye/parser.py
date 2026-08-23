"""龙眼期权 (DragonEye Options) Markdown 结构解析器 (MarkdownParser)

根据工程规范第 3 节标准骨架解析 Markdown 研报/剧本，提取元数据与结构化区块。

# Modification History
| Version | Date       | Author                       | Description |
|---------|------------|------------------------------|-------------|
| 1.0.0   | 2026-08-21 | Gemini_3.7_Flash_High_planning | 初始创建 Markdown 规范解析器，支持流动性、雷达、推演与风控区块提取 |
"""

import re
from typing import Dict, Any, List


def _format_inline_values(text: str) -> str:
    """格式化行内数值、价格与关键词高亮"""
    # 替换价格与数值：如 $602.50, $600 ~ $605, Call $605 / Put $595
    # 高亮美元点位
    text = re.sub(
        r'(\$[\d\.,]+)',
        r'<span class="num-cyan">\1</span>',
        text
    )
    # 高亮百分比
    text = re.sub(
        r'(\d+[\.\d]*%)',
        r'<span class="num-gold">\1</span>',
        text
    )
    # 处理加粗 **...** -> <strong>...</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 处理斜体 *...* -> <em>...</em>
    text = re.sub(r'\*([^\*]+?)\*', r'<em>\1</em>', text)
    return text.strip()


def parse_dragon_eye_markdown(md_text: str) -> Dict[str, Any]:
    """
    解析龙眼期权标准 Markdown 文本，返回渲染所需的数据字典。
    """
    lines = [line.strip() for line in md_text.strip().split("\n")]
    
    result: Dict[str, Any] = {
        "column_name": "盘前剧本",
        "trading_date": "",
        "issue_no": "",
        "engine_name": "OptionSense",
        "sections": [],
        "motto": "👁️ 龙眼期权 | 穿透微观流动性 · 捕捉日内确定性",
        "disclaimer": "⚠️ 免责声明：本内容基于期权微观量化模型推演，仅供实战交流，不构成直接投资建议。",
        "raw_content_html": ""
    }

    # 1. 提取头部元数据
    # 匹配: 🐉 **龙眼期权 · DRAGONEYE OPTIONS** | **[栏目名称：盘前剧本 / 每日复盘]**
    for line in lines[:10]:
        if "龙眼期权" in line or "DRAGONEYE" in line:
            col_match = re.search(r'\[(?:栏目名称：)?([^\]]+)\]', line)
            if col_match:
                result["column_name"] = col_match.group(1).strip()
            elif "盘前剧本" in line:
                result["column_name"] = "盘前剧本"
            elif "每日复盘" in line:
                result["column_name"] = "每日复盘"
            elif "周度研报" in line:
                result["column_name"] = "周度研报"

        # 匹配: 📅 交易日：YYYY-MM-DD | 编号：No.XXX | 核心引擎：OptionSense
        if "交易日" in line or "📅" in line:
            date_match = re.search(r'交易日[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', line)
            if date_match:
                result["trading_date"] = date_match.group(1).strip()
            
            no_match = re.search(r'编号[：:]\s*(No\.[A-Za-z0-9_\-]+|\d+)', line)
            if no_match:
                result["issue_no"] = no_match.group(1).strip()

            eng_match = re.search(r'核心引擎[：:]\s*([A-Za-z0-9_\-]+)', line)
            if eng_match:
                result["engine_name"] = eng_match.group(1).strip()

    # 2. 按大区块切分
    # 将文本按标题/分界线组织
    content_text = md_text
    
    # 提取 【龙眼定点】
    liquidity_sec = {"type": "liquidity", "title": "【龙眼定点】核心流动性分布", "metrics": []}
    liquidity_match = re.search(r'🎯\s*\*\*【龙眼定点】[^\n]*\*\*(.*?)(?=⚡|🗡️|🛡️|━━|$)', content_text, re.DOTALL)
    if liquidity_match:
        items_block = liquidity_match.group(1)
        for item_line in items_block.strip().split("\n"):
            item_line = item_line.strip()
            if not item_line or not item_line.startswith("*"):
                continue
            # 格式: * **Gamma Wall（多空分水岭）**: $XXX.XX
            m = re.search(r'\*\s*\*\*([^\*]+)\*\*[：:]\s*(.*)', item_line)
            if m:
                label = m.group(1).strip()
                val = _format_inline_values(m.group(2))
                liquidity_sec["metrics"].append({"label": label, "value": val})
        if liquidity_sec["metrics"]:
            result["sections"].append(liquidity_sec)

    # 提取 【异动雷达】
    radar_sec = {"type": "radar", "title": "【异动雷达】主力扫单与 IV 追踪", "metrics": []}
    radar_match = re.search(r'⚡\s*\*\*【异动雷达】[^\n]*\*\*(.*?)(?=🎯|🗡️|🛡️|━━|$)', content_text, re.DOTALL)
    if radar_match:
        items_block = radar_match.group(1)
        for item_line in items_block.strip().split("\n"):
            item_line = item_line.strip()
            if not item_line or not item_line.startswith("*"):
                continue
            m = re.search(r'\*\s*\*\*([^\*]+)\*\*[：:]\s*(.*)', item_line)
            if m:
                label = m.group(1).strip()
                val = _format_inline_values(m.group(2))
                radar_sec["metrics"].append({"label": label, "value": val})
        if radar_sec["metrics"]:
            result["sections"].append(radar_sec)

    # 提取 【剧本推演 / 胜负手】
    scenarios_sec = {"type": "scenarios", "title": "【剧本推演 / 胜负手】战术应对", "scenarios": []}
    scenarios_match = re.search(r'🗡️\s*\*\*【剧本推演[^\n]*\*\*(.*?)(?=🎯|⚡|🛡️|━━|$)', content_text, re.DOTALL)
    if scenarios_match:
        items_block = scenarios_match.group(1)
        for item_line in items_block.strip().split("\n"):
            item_line = item_line.strip()
            if not item_line or not item_line.startswith("*"):
                continue
            # 格式: * **情境 A（多头突破）**: 放量站上 $XXX.XX...
            m = re.search(r'\*\s*\*\*([^\*]+)\*\*[：:]\s*(.*)', item_line)
            if m:
                title = m.group(1).strip()
                body = _format_inline_values(m.group(2))
                variant = "bull" if ("多头" in title or "A" in title or "突破" in title) else "bear"
                icon = "🟢" if variant == "bull" else "🔴"
                scenarios_sec["scenarios"].append({
                    "title": title,
                    "body": body,
                    "variant": variant,
                    "icon": icon
                })
        if scenarios_sec["scenarios"]:
            result["sections"].append(scenarios_sec)

    # 提取 【风控红线】
    risk_sec = {"type": "risk", "title": "【风控红线】", "content": ""}
    risk_match = re.search(r'🛡️\s*\*\*【风控红线】\*\*(.*?)(?=━━|👁️|⚠️|$)', content_text, re.DOTALL)
    if risk_match:
        risk_body = risk_match.group(1).strip()
        # 清除开头的 * 号
        risk_lines = [re.sub(r'^\*\s*', '', l.strip()) for l in risk_body.split("\n") if l.strip()]
        risk_html = "<br/>".join([_format_inline_values(l) for l in risk_lines])
        risk_sec["content"] = risk_html
        if risk_sec["content"]:
            result["sections"].append(risk_sec)

    # 如果没有任何匹配的特定区块，则生成回退 Generic Blocks
    if not result["sections"]:
        result["raw_content_html"] = "<br/>".join([_format_inline_values(l) for l in lines if l and not l.startswith("━")])

    return result
