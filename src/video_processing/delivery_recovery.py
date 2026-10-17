"""将恢复动作绑定到失败实例、当前账本和原始产物；不接受客户端路径。"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from .utils.retry_policy import failure_kind

BACKEND_URL = "https://channels.weixin.qq.com/platform/post/list"


def file_fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


class DeliveryRecoveryService:
    def __init__(self, db, root: Path):
        self.db, self.root = db, Path(root).resolve()

    def register_production(self, request_path: Path, detail: str, *, allow_retry=False):
        path = Path(request_path).resolve()
        if not path.is_relative_to(self.root / "output/english_world_daily"):
            raise ValueError("恢复请求不属于英语世界运行目录")
        request = json.loads(path.read_text())
        if request.get("kind") != "failure":
            raise ValueError("已有成片交付请求不能重做生产")
        payload = {"request": file_fingerprint(path), "allow_retry": bool(allow_retry)}
        return self.db.create_delivery_recovery(
            event_key="ew:" + str(path), kind="EW_PRODUCTION", payload=payload,
            detail=detail, failure_kind=failure_kind(detail))

    def register_unknown(self, youtube_id: str, slice_index=0):
        video = self.db.get_video_by_youtube_id(youtube_id, slice_index)
        pub = self.db.get_wechat_publication(youtube_id, slice_index=slice_index)
        if not video or not pub or video["status"] != "UNCERTAIN" or pub["state"] != "UNCERTAIN":
            raise ValueError("当前任务不处于投稿结果未知状态")
        prefix = f"{youtube_id}_s{slice_index}" if slice_index else youtube_id
        # 绑定实际发布所需文件；重传仍须通过原发布链的词汇/内容/封面门禁。
        artifacts = [file_fingerprint(p) for p in sorted((self.root / "output").glob(prefix + "*"))
                     if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(self.root / 'output')
                     and not (slice_index == 0 and p.name.startswith(youtube_id + '_s'))
                     and p.suffix in {".mp4", ".txt", ".ass", ".jpg", ".json"}]
        payload = {"video_id": video["id"], "youtube_id": youtube_id, "slice_index": slice_index,
                   "title": video.get("title") or youtube_id, "video_updated_at": video["updated_at"],
                   "video_retry_count": video.get("retry_count"),
                   "publication_updated_at": pub["updated_at"], "artifacts": artifacts}
        return self.db.create_delivery_recovery(
            event_key=f"wechat:{pub['id']}:{pub['updated_at']}", kind="WECHAT_UNKNOWN",
            payload=payload, detail=pub.get("error_message") or "未取得平台受理证明；尚未核验后台",
            failure_kind="SUBMISSION_UNKNOWN")

    def view(self, recovery_id: str):
        row = self.db.get_delivery_recovery(recovery_id)
        if not row:
            raise ValueError("恢复任务不存在")
        p = json.loads(row["payload_json"])
        text = (f"恢复编号：{row['id'][:8]}\n类型：{row['kind']}\n状态：{row['state']}\n"
                f"原因：{row['detail']}\n分类：{row['failure_kind']}\n执行次数：{row['attempts']}/3\n"
                f"下次执行：{row['next_attempt_at'] or '未安排'} UTC\n按钮有效至：{row['expires_at']} UTC")
        if row.get("result"):
            text += "\n执行结果：" + row["result"]
        if row["kind"] == "WECHAT_UNKNOWN":
            text += (f"\n标题：{p['title']}\nID：{p['youtube_id']}\n已绑定产物：{len(p['artifacts'])} 个"
                     "\n后台核验：须同时检查已发表、审核中、草稿。打开后台不等于已核验。"
                     "\n只有确认本条均不存在，才能使用人工确认重传。")
        else:
            text += "\n重试沿用日常制作与发布策略，重新检查库存、上限和已投稿保护。"
            if not p.get("allow_retry"):
                text += "\n此实例只提供查看；手工选题请在 /english_world 重新确认制作。"
        return {"id": row["id"], "text": text, "reply_markup": keyboard(row)}

    def validate_confirmed_artifacts(self, youtube_id, slice_index=0):
        for item in self.db.get_confirmed_recovery_artifacts(youtube_id, slice_index):
            path = Path(item['path'])
            if not path.is_relative_to(self.root / 'output') or file_fingerprint(path) != item:
                raise ValueError('人工确认后的发布包已变化，需重新核验，未重新上传')

    def act(self, recovery_id: str, *, action: str, actor: str):
        row = self.db.get_delivery_recovery(recovery_id)
        if not row:
            raise ValueError("恢复任务不存在")
        payload = json.loads(row["payload_json"])
        if action == "confirm":
            if row["kind"] != "WECHAT_UNKNOWN" or not payload["artifacts"]:
                raise ValueError("缺少绑定产物，不能重传")
            if not any(a["path"].endswith(".mp4") for a in payload["artifacts"]):
                raise ValueError("没有绑定成片，不能重传")
            for item in payload["artifacts"]:
                path = Path(item["path"])
                if not path.is_relative_to(self.root / "output") or file_fingerprint(path) != item:
                    raise ValueError("产物已变化，请刷新任务后重新核验")
            self.db.confirm_unpublished_delivery_recovery(recovery_id, actor=actor)
        elif action in {"retry", "hold"}:
            if action == "retry":
                if row["kind"] != "EW_PRODUCTION" or not payload.get("allow_retry"):
                    raise ValueError("此实例未授权通用生产重试")
                item = payload["request"]
                if file_fingerprint(Path(item["path"])) != item:
                    raise ValueError("原运行记录已变化，请刷新")
                if json.loads(Path(item["path"]).read_text()).get("kind") != "failure":
                    raise ValueError("已有交付产物，禁止重做")
            self.db.queue_delivery_recovery(recovery_id, action=action, actor=actor)
        elif action != "view":
            raise ValueError("未知恢复动作")
        return self.view(recovery_id)


def keyboard(row: dict) -> dict:
    rid = row["id"]
    buttons = [[{"text": "🔎 查看原因与最新状态", "callback_data": f"recover:view:{rid}"}]]
    if row["kind"] == "WECHAT_UNKNOWN":
        buttons += [[{"text": "打开视频号后台核验", "url": BACKEND_URL}]]
        if row["state"] == "WAITING":
            buttons += [[{"text": "我已核验未发布，申请重传", "callback_data": f"recover:ask:{rid}"}]]
    elif row["state"] == "WAITING" and json.loads(row["payload_json"]).get("allow_retry"):
        buttons += [[{"text": "▶️ 恢复制作", "callback_data": f"recover:retry:{rid}"}]]
    if row["state"] == "WAITING":
        buttons += [[{"text": "⏸ 暂停此恢复", "callback_data": f"recover:hold:{rid}"}]]
    return {"inline_keyboard": buttons}


def notice(view: dict) -> str:
    return "<b>任务恢复状态</b>\n" + html.escape(view["text"])
