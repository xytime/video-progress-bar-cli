"""高互动列表的展示与操作契约，不执行任务。

依赖方向：web.app → 本模块；db.database 提供统一阶段（含分页前筛选）。
本模块仅使用标准库，不导入 Web、DAL 或调度器。
"""
import hashlib
import json


STAGES = {
    "ENG_DISCOVERY": ("仅供选题", "尚未加入生产队列", "neutral", "promote"),
    "ENG_UNSCORED": ("待评分", "尚无评分结果，未自动入队", "neutral", "promote"),
    "ENG_LOW_SCORE": ("未达入队分数", "评分未达到自动入队标准", "muted", "promote"),
    "ENG_PENDING": ("待加工", "评分已入围，等待调度；可手动启动", "neutral", "process"),
    "ENG_ACTIVE": ("加工中", "任务正在执行，请勿重复启动", "info", None),
    "ENG_POLICY": ("规则拦截", "按现有错误记录识别，需人工复核", "warning", "bypass-censor"),
    "ENG_FAILED": ("处理失败", "查看错误后决定是否重试；重试沿用已有产物", "danger", "retry"),
    "ENG_LOGIN": ("等待登录", "先恢复平台登录，再重试处理", "warning", None),
    "ENG_READY": ("成片就绪", "加工完成，等待后续发布流程", "info", None),
    "ENG_SUBMITTED": ("已提交，待确认发布", "平台已受理，尚未确认公开发布", "info", None),
    "ENG_REVIEW": ("平台审核中", "等待平台结果，不能重复提交", "info", None),
    "ENG_PUBLISHED": ("已有确认发布记录", "至少一个平台已记录发布确认；各平台状态见详情", "success", None),
    "ENG_VERIFY": ("发布记录待核实", "存在平台队列、投稿或本地完成记录，请先核实，不能重新入队", "warning", None),
    "ENG_SEGMENTED": ("已拆分加工", "查看各分集的进度与失败原因", "info", None),
    "ENG_EXCLUDED": ("已排除", "已忽略、归档或受准入规则限制", "muted", None),
    "ENG_UNKNOWN": ("状态待核实", "当前记录不足以确定可执行操作", "muted", None),
}
ACTION_LABELS = {
    "promote": "人工选用并入队", "process": "开始处理",
    "retry": "重试处理", "bypass-censor": "复核放行",
}
ACTIVE_LABELS = {
    "DOWNLOADING": "下载中", "COPYWRITING": "文案处理中", "TRANSCRIBING": "字幕处理中",
    "RENDERING": "视频渲染中", "AI_COVER_PENDING": "封面待生成",
    "PUBLISH_PRECHECK": "发布前检查", "PUBLISHING": "正在提交平台",
}


def present_engagement(video: dict) -> dict:
    """阶段由 DAL 决定，版本绑定当前任务及平台状态；浏览标记不改变动作资格。"""
    stage = video.get("engagement_stage", "ENG_UNKNOWN")
    label, reason, tone, action = STAGES.get(stage, STAGES["ENG_UNKNOWN"])
    if stage == "ENG_LOW_SCORE":
        reason = f"当前 {video.get('score', 0)} 分，自动入队线 {video.get('engagement_score_line', 75)} 分"
    if stage == "ENG_ACTIVE":
        label = ACTIVE_LABELS.get(video.get("status"), label)
    if video.get("publication_review_required") and stage == "ENG_VERIFY":
        reason = "该任务要求人工复核，暂不能从高互动列表重新启动"
    if stage in {"ENG_POLICY", "ENG_FAILED", "ENG_PENDING", "ENG_LOGIN", "ENG_READY"}:
        reason = video.get("publication_wait_reason") or video.get("error_msg") or reason
    if stage == "ENG_FAILED" and (video.get("score") or 0) < 75:
        reason += "；当前低于重试接口的 75 分启动线，重试只恢复待筛选"
    # DISCOVERY 的失败不能走通用重试恢复生产，必须在可选用状态显式转换来源。
    if video.get("source") == "DISCOVERY" and stage != "ENG_DISCOVERY":
        action = None
    if stage == "ENG_UNSCORED" and video.get("status") != "PENDING":
        action = None
        reason = "元数据尚未准备完成，等待采集后再选用"
    if video.get("process_pid") and stage in {"ENG_FAILED", "ENG_POLICY", "ENG_PENDING"}:
        action = None
        reason += "；仍有执行进程记录，请先核实运行状态"
    version_data = {key: video.get(key) for key in (
        "id", "youtube_id", "slice_index", "status", "source", "score", "updated_at",
        "error_msg", "censor_tag", "bypass_censorship", "preparation_ready", "process_pid",
        "engagement_stage", "engagement_score_line", "publication_review_required", "platforms",
    )}
    version = hashlib.sha256(json.dumps(version_data, sort_keys=True, ensure_ascii=False,
                                       default=str).encode()).hexdigest()
    return {
        "stage": stage, "label": label, "reason": reason, "tone": tone,
        "action": action, "action_label": ACTION_LABELS.get(action, ""), "version": version,
    }
