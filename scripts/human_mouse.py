"""human_mouse.py — 人类鼠标行为模拟工具

微信视频号平台会检测自动化操作的多种特征：
  - isTrusted=false (程序点击的 click 事件)
  - 缺少 pointerdown/pointerup/mousedown/mouseup 事件序列
  - 点击坐标完全精确 (真人不会点到像素级精准)
  - 操作间隔过于规律

本模块提供：
  1. human_click(page, locator) — 模拟人类鼠标点击（移动→hover→click）
  2. human_check(page, locator) — 模拟人类勾选 checkbox
  3. find_and_click_text(page, texts) — 用文字找元素后人类点击
  4. wait_and_click(page, selector, timeout_s) — 等待可点击后人类点击

# Modification History
| Version | Date       | Author                              | Description |
|---------|------------|-------------------------------------|-------------|
| 1.0.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 初建，反反爬虫人类行为模拟库 |
"""

import random
import time
import logging
import math
from typing import Optional, List, Union

logger = logging.getLogger("human_mouse")


# ── 随机化工具 ────────────────────────────────────────────────────────────────

def _jitter(value: float, spread: float = 3.0) -> float:
    """给坐标加随机抖动，模拟人手不稳"""
    return value + random.gauss(0, spread)


def _human_delay(min_ms: int = 80, max_ms: int = 250):
    """随机延迟（毫秒），模拟人类反应时间"""
    ms = random.randint(min_ms, max_ms)
    time.sleep(ms / 1000.0)


def _bezier_points(x0, y0, x1, y1, steps=8):
    """生成贝塞尔曲线路径点，模拟鼠标自然移动轨迹"""
    # 控制点随机偏移
    cx = (x0 + x1) / 2 + random.uniform(-40, 40)
    cy = (y0 + y1) / 2 + random.uniform(-40, 40)
    points = []
    for i in range(steps + 1):
        t = i / steps
        # 二次贝塞尔: P = (1-t)^2*P0 + 2(1-t)t*C + t^2*P1
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
        points.append((x, y))
    return points


# ── 核心函数 ──────────────────────────────────────────────────────────────────

def get_element_center(locator) -> Optional[tuple]:
    """获取元素中心坐标，返回 (x, y) 或 None"""
    try:
        box = locator.bounding_box()
        if box:
            x = box['x'] + box['width'] / 2
            y = box['y'] + box['height'] / 2
            return (x, y)
    except Exception:
        pass
    return None


def human_move_to(page, x: float, y: float, from_x: float = None, from_y: float = None):
    """沿贝塞尔曲线自然地将鼠标移动到目标坐标"""
    try:
        # 获取当前鼠标位置（如未知则从屏幕边缘出发）
        if from_x is None:
            from_x = random.uniform(50, 200)
        if from_y is None:
            from_y = random.uniform(50, 200)

        # 贝塞尔曲线路径
        steps = random.randint(6, 12)
        points = _bezier_points(from_x, from_y, x, y, steps)

        for px, py in points:
            page.mouse.move(_jitter(px, 1.5), _jitter(py, 1.5))
            # 不均匀的步间延迟
            time.sleep(random.uniform(0.01, 0.04))
    except Exception as e:
        logger.debug(f"Mouse move failed: {e}")


def human_click(page, locator, *, retries: int = 3, scroll_into_view: bool = True) -> bool:
    """人类化点击：移动鼠标 → hover → 随机延迟 → click（完整事件序列）
    
    避免使用 force=True（会跳过 hover/focus 检测）。
    使用 page.mouse 模拟真实坐标点击，产生 isTrusted=true 的事件。
    """
    for attempt in range(retries):
        try:
            if scroll_into_view:
                try:
                    locator.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

            center = get_element_center(locator)
            if center is None:
                logger.debug(f"Attempt {attempt}: bounding box not available, using locator.click()")
                _human_delay(100, 300)
                locator.click(timeout=3000)
                return True

            tx, ty = center
            # 在元素范围内随机偏移（不总是点击正中心）
            try:
                box = locator.bounding_box()
                offset_x = random.uniform(-box['width'] * 0.25, box['width'] * 0.25)
                offset_y = random.uniform(-box['height'] * 0.25, box['height'] * 0.25)
                tx += offset_x
                ty += offset_y
            except Exception:
                pass

            # 自然移动到元素附近
            human_move_to(page, tx, ty)

            # 模拟 hover 停留
            _human_delay(80, 200)

            # 真实鼠标点击（产生完整事件序列: pointerdown/mousedown/pointerup/mouseup/click）
            page.mouse.click(tx, ty)
            logger.debug(f"human_click: clicked at ({tx:.1f}, {ty:.1f})")
            return True

        except Exception as e:
            logger.debug(f"human_click attempt {attempt} failed: {e}")
            _human_delay(300, 600)

    return False


def human_check(page, locator) -> bool:
    """人类化勾选 checkbox — 先检查是否已选，再点击"""
    try:
        # 如果已经选中，不需要再点击
        try:
            if locator.is_checked():
                logger.debug("Checkbox already checked, skipping")
                return True
        except Exception:
            pass

        return human_click(page, locator)
    except Exception as e:
        logger.debug(f"human_check failed: {e}")
        return False


def find_and_human_click_text(page, texts: List[str],
                               exclude_disabled: bool = True,
                               timeout_polls: int = 15) -> bool:
    """用文字内容找元素，然后人类化点击。
    
    比 CSS class 更稳定，微信更新 UI 时文字通常不变。
    会轮询等待按钮从 disabled 变为 enabled。
    """
    for poll in range(timeout_polls):
        if poll > 0:
            _human_delay(800, 1500)

        for text in texts:
            # 用 Playwright 的文字定位
            btn = page.locator(f"button:has-text('{text}')").last
            if btn.count() == 0:
                # 尝试更宽泛的选择器
                btn = page.get_by_text(text, exact=True).last

            if btn.count() == 0:
                continue

            try:
                if not btn.is_visible(timeout=500):
                    continue
            except Exception:
                continue

            if exclude_disabled:
                try:
                    if btn.get_attribute("disabled") is not None:
                        logger.debug(f"[poll {poll}] '{text}' is disabled, waiting...")
                        continue
                    if btn.get_attribute("aria-disabled") == "true":
                        logger.debug(f"[poll {poll}] '{text}' aria-disabled, waiting...")
                        continue
                except Exception:
                    pass

            # 找到了可用的按钮，人类化点击
            ok = human_click(page, btn)
            if ok:
                logger.info(f"find_and_human_click_text: clicked '{text}' on poll {poll}")
                return True

    logger.warning(f"find_and_human_click_text: none of {texts} became clickable")
    return False


def find_checkbox_near_text(page, keywords: List[str]) -> Optional[object]:
    """找包含关键词文字附近的 checkbox locator"""
    for keyword in keywords:
        for sel in [
            f"label:has-text('{keyword}') input[type='checkbox']",
            f"input[type='checkbox']:near(:text('{keyword}'))",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=500):
                    return loc.first
            except Exception:
                pass

    # JS 遍历兜底：找可见的 checkbox
    try:
        result = page.evaluate("""(keywords) => {
            const cbs = document.querySelectorAll('input[type="checkbox"]');
            for (const cb of cbs) {
                if (cb.offsetParent === null) continue;
                const parent = cb.closest('label, div, span, li') || cb.parentElement;
                const parentText = parent?.innerText || '';
                const nearby = keywords.some(k => parentText.includes(k));
                if (nearby || cbs.length === 1) {  // 弹窗内只有一个时直接用
                    return {found: true, xpath: cb.id || ''};
                }
            }
            return {found: false};
        }""", keywords)

        if result and result.get('found'):
            # 返回所有可见 checkbox 中的第一个
            loc = page.locator("input[type='checkbox']:visible").first
            if loc.count() > 0:
                return loc
    except Exception:
        pass

    return None


def dispatch_human_click_events(page, locator) -> bool:
    """终极兜底：手动派发完整的鼠标事件序列（模拟 isTrusted 行为）
    
    当普通 click 被检测时使用。注意: 这里仍然 isTrusted=false，
    但完整的事件序列能绕过部分简单检测。
    """
    try:
        box = locator.bounding_box()
        if not box:
            return False

        cx = box['x'] + box['width'] / 2 + random.uniform(-3, 3)
        cy = box['y'] + box['height'] / 2 + random.uniform(-3, 3)

        # 移动鼠标到元素
        page.mouse.move(cx, cy)
        time.sleep(random.uniform(0.05, 0.15))

        # 模拟完整点击序列
        page.mouse.down()
        time.sleep(random.uniform(0.05, 0.12))
        page.mouse.up()

        logger.debug(f"dispatch_human_click_events: dispatched at ({cx:.1f}, {cy:.1f})")
        return True
    except Exception as e:
        logger.debug(f"dispatch_human_click_events failed: {e}")
        return False
