"""人工配音版的 DeepSeek 中文脚本精修器。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-29 | Codex | 对齐英文原文精修普通话配音稿；强制逐段 JSON 对齐并支持 DeepSeek thinking |
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from config.settings import settings


class DubbingScriptRefiner:
    """只精修人工配音文本；不读取数据库，也不触发渲染或发布。"""

    def refine(self, chunks: List[Dict[str, Any]], *, video_title: str) -> List[Dict[str, Any]]:
        if not settings.deepseek_api_key:
            raise RuntimeError("DeepSeek 脚本精修已启用，但 DEEPSEEK_API_KEY 未配置。")
        if not chunks:
            return []

        refined: List[Dict[str, Any]] = []
        batch_size = settings.dubbing_deepseek_refinement_batch_size
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            rewrites = self._refine_batch(batch, video_title=video_title)
            for chunk, zh_text in zip(batch, rewrites):
                item = dict(chunk)
                item["zh_text"] = zh_text
                refined.append(item)
        return refined

    def _refine_batch(self, chunks: List[Dict[str, Any]], *, video_title: str) -> List[str]:
        items = [
            {
                "id": index,
                "english": str(chunk.get("source_text") or ""),
                "draft_zh": str(chunk.get("zh_text") or ""),
            }
            for index, chunk in enumerate(chunks)
        ]
        prompt = (
            "You are the final Mandarin dialogue editor for a finance and technology video. "
            "Rewrite every draft_zh against its English source into natural, concise spoken zh-CN. "
            "Preserve every material fact, number, percentage, company name, ticker, person, causal direction, "
            "and uncertainty. Do not add facts, explanations, marketing language, or English-learning notes. "
            "Use natural Chinese sentence punctuation so a subtitle renderer can paginate by complete sentences. "
            "Keep each item within its source segment; do not merge or split ids. "
            f"Video title context: {video_title}\n"
            "Return JSON only in exactly this shape: {\"items\":[{\"id\":0,\"zh_text\":\"...\"}]}.\n"
            f"Input: {json.dumps(items, ensure_ascii=False)}"
        )
        payload: Dict[str, Any] = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "You are a meticulous Chinese subtitle editor. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.15,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if settings.dubbing_deepseek_thinking_enabled:
            payload["thinking"] = {"type": "enabled"}

        request = urllib.request.Request(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.deepseek_api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"DeepSeek 脚本精修 HTTP {exc.code}，已停止任务。") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"DeepSeek 脚本精修请求失败，已停止任务：{type(exc).__name__}") from exc

        try:
            content = str(data["choices"][0]["message"]["content"] or "")
            parsed = json.loads(content.strip().removeprefix("```json").removesuffix("```").strip())
            rows = parsed["items"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("DeepSeek 脚本精修未返回可解析的 JSON，已停止任务。") from exc

        aligned: List[str | None] = [None] * len(chunks)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            index = row.get("id")
            text = str(row.get("zh_text") or "").strip()
            if isinstance(index, int) and 0 <= index < len(aligned) and text:
                aligned[index] = text
        if any(text is None for text in aligned):
            raise RuntimeError("DeepSeek 脚本精修返回的段落数量或 ID 不完整，已停止任务。")
        return [str(text) for text in aligned]
