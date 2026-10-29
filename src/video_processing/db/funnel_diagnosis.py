"""入库批次流程概览与异常诊断只读数据访问层（DAL）。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.3.0 | 2026-10-29 | Codex | 关联查询失败显式上抛、全查询绑定参数不超过400，使用只读一致性快照并透传入库来源。 |
| 1.2.0 | 2026-10-29 | Antigravity | 补充 get_cohort_task_facts 别名以兼容服务层门面调用。 |
| 1.1.0 | 2026-10-29 | Antigravity | 优化 ISO 时间解析（支持 Z/+00:00）、分块查询防 SQLite 溢出、退避保留最大时刻与行转换拆分。 |
| 1.0.0 | 2026-10-29 | Antigravity | 初始创建入库批次主任务族与分集全量关联事件只读查询 Mixin。 |
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Optional, Sequence

from ..funnel_diagnosis.models import TaskUnitFacts

MAX_IN_VARS = 400


def _parse_iso_or_epoch(raw: Any) -> Optional[float]:
    """安全解析时间戳为 Unix epoch 秒数（支持 float、int、UTC ISO、Z 格式及 SQLite 格式）。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = str(raw).strip()
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError):
        pass
    cleaned_space = cleaned.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned_space[:26], fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        return float(cleaned)
    except ValueError:
        return None


def _chunk_list(items: Sequence[Any], size: int = MAX_IN_VARS) -> list[list[Any]]:
    """将序列按指定块大小切分，防止超过 SQLite 参数上限。"""
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _safe_query(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    """只读执行查询；失败必须上抛，禁止将缺表、损坏或锁冲突伪装成无事件。"""
    if len(params) > MAX_IN_VARS:
        raise ValueError("Diagnosis query exceeds SQL parameter budget")
    return conn.execute(sql, tuple(params)).fetchall()


def _start_read_snapshot(conn: sqlite3.Connection) -> None:
    """连接级禁止写入，并使任务与所有关联证据读取同一数据库快照。"""
    conn.execute("PRAGMA query_only = ON")
    conn.execute("BEGIN")


def _build_funnel_cohort_where(
    window: Optional[str] = "today_bj",
    channel_id: Optional[str] = None,
    days: Optional[int] = None,
    since_time: Optional[str] = None,
    until_time: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """构建入库批次主任务（parent_id IS NULL）的时间窗口与频道筛选条件。"""
    clauses: list[str] = ["pv.parent_id IS NULL"]
    params: list[Any] = []
    if channel_id and channel_id not in ("all", "*", ""):
        clauses.append("(pv.channel_id = ? OR rc.channel_name = ?)")
        params.extend([channel_id, channel_id])
    if since_time:
        clauses.append("pv.created_at >= ?")
        params.append(since_time)
    if until_time:
        clauses.append("pv.created_at <= ?")
        params.append(until_time)
    if not since_time and not until_time:
        w_map = {
            "24h": "pv.created_at >= datetime('now', '-24 hours')",
            "today_bj": "pv.created_at >= datetime(date('now', '+8 hours'), '-8 hours')",
            "7d": "pv.created_at >= datetime('now', '-7 days')",
            "30d": "pv.created_at >= datetime('now', '-30 days')",
        }
        if window in w_map:
            clauses.append(w_map[window])
        elif days and days > 0:
            clauses.append(f"pv.created_at >= datetime('now', '-{int(days)} days')")
    return " AND ".join(clauses), params


def _fetch_cohort_family_rows(
    conn: sqlite3.Connection, where_clause: str, params: list[Any]
) -> list[sqlite3.Row]:
    """先通过批次条件获取主任务 ID，再分块连同其切片分集任务一同按族排序取出。"""
    root_sql = (
        "SELECT pv.id FROM processed_videos pv "
        "LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id "
        f"WHERE {where_clause} ORDER BY pv.id ASC"
    )
    root_rows = _safe_query(conn, root_sql, params)
    root_ids = [r["id"] for r in root_rows]
    if not root_ids:
        return []
    all_rows: list[sqlite3.Row] = []
    for chunk in _chunk_list(root_ids, size=MAX_IN_VARS // 2):
        placeholders = ",".join("?" for _ in chunk)
        family_sql = (
            "SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id, '') AS channel_name "
            "FROM processed_videos pv LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id "
            f"WHERE pv.id IN ({placeholders}) OR pv.parent_id IN ({placeholders}) "
            "ORDER BY COALESCE(pv.parent_id, pv.id) ASC, pv.slice_index ASC, pv.id ASC"
        )
        all_rows.extend(_safe_query(conn, family_sql, chunk + chunk))
    return all_rows


def _fetch_failure_events(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> dict[int, list[dict[str, Any]]]:
    """批量分块查询发布失败事件，并补充解析 failed_epoch。"""
    if not video_ids:
        return {}
    res: dict[int, list[dict[str, Any]]] = {}
    for chunk in _chunk_list(video_ids):
        placeholders = ",".join("?" for _ in chunk)
        sql = (
            "SELECT id, video_id, status, reason, failed_at FROM publishing_failure_events "
            f"WHERE video_id IN ({placeholders}) ORDER BY failed_at DESC, id DESC"
        )
        for r in _safe_query(conn, sql, chunk):
            item = dict(r)
            item["failed_epoch"] = _parse_iso_or_epoch(item.get("failed_at"))
            res.setdefault(item["video_id"], []).append(item)
    return res


def _fetch_recovery_items(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> dict[int, list[dict[str, Any]]]:
    """批量分块查询恢复项，并左连接所属批次操作的最新状态 (op_state)。"""
    if not video_ids:
        return {}
    res: dict[int, list[dict[str, Any]]] = {}
    for chunk in _chunk_list(video_ids):
        placeholders = ",".join("?" for _ in chunk)
        sql = (
            "SELECT i.id, i.operation_id, i.video_id, i.position, i.state, i.reason, "
            "i.next_at, i.original, i.current_revision, i.started, i.updated, "
            "i.permit_expires, i.permit_used, o.state AS op_state "
            "FROM publishing_recovery_items i "
            "LEFT JOIN publishing_recovery_operations o ON o.id = i.operation_id "
            f"WHERE i.video_id IN ({placeholders}) ORDER BY i.updated DESC, i.id DESC"
        )
        for r in _safe_query(conn, sql, chunk):
            res.setdefault(r["video_id"], []).append(dict(r))
    return res


def _fetch_subtitle_recoveries(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """批量分块查询每个任务当前的字幕修复状态记录 (is_current = 1)。"""
    if not video_ids:
        return {}
    res: dict[int, dict[str, Any]] = {}
    for chunk in _chunk_list(video_ids):
        placeholders = ",".join("?" for _ in chunk)
        sql = (
            "SELECT id, video_id, input_sha256, contract_sha256, is_current, state, "
            "attempt_count, chain_started_at, expires_at, next_attempt_at, failure_fingerprint, "
            "category, code, quality_details, last_receipt_path, last_receipt_sha, evidence_path, "
            "released_receipt_sha, updated_at FROM subtitle_recovery "
            f"WHERE video_id IN ({placeholders}) AND is_current = 1"
        )
        for r in _safe_query(conn, sql, chunk):
            res[r["video_id"]] = dict(r)
    return res


def _fetch_delivery_recoveries(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> dict[int, list[dict[str, Any]]]:
    """批量查询投递恢复项，支持 payload_json 内嵌 video_id 关联。"""
    if not video_ids:
        return {}
    res: dict[int, list[dict[str, Any]]] = {}
    targets = set(video_ids)
    rows = _safe_query(conn, "SELECT * FROM delivery_recoveries WHERE payload_json LIKE '%video_id%'")
    for r in rows:
        d = dict(r)
        raw_p = d.get("payload_json")
        if not raw_p:
            continue
        p = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
        if not isinstance(p, dict):
            raise ValueError("Invalid delivery recovery evidence")
        vid = p.get("video_id")
        if vid is not None and int(vid) in targets:
            res.setdefault(int(vid), []).append(d)
    return res


def _fetch_wechat_publications(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> tuple[dict[int, dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    """批量分块查询微信发布记录与提交尝试记录。"""
    pubs: dict[int, dict[str, Any]] = {}
    attempts: dict[int, list[dict[str, Any]]] = {}
    if not video_ids:
        return pubs, attempts
    for chunk in _chunk_list(video_ids):
        placeholders = ",".join("?" for _ in chunk)
        pub_sql = (
            "SELECT id, video_id, subject_id, state, evidence_path, confirmed_at, "
            "platform_post_id, platform_url, last_reconciled_at, last_error_message, "
            f"created_at, updated_at FROM wechat_publications WHERE video_id IN ({placeholders})"
        )
        for r in _safe_query(conn, pub_sql, chunk):
            pubs[r["video_id"]] = dict(r)
        att_sql = (
            "SELECT attempt_id, video_id, subject_id, evidence_path, "
            "platform_post_id, state, created_at FROM wechat_submission_attempts "
            f"WHERE video_id IN ({placeholders}) ORDER BY created_at DESC"
        )
        for r in _safe_query(conn, att_sql, chunk):
            attempts.setdefault(r["video_id"], []).append(dict(r))
    return pubs, attempts


def _fetch_backoffs(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> tuple[dict[int, float], dict[int, float]]:
    """批量分块查询上传重试与文案退避，保留各任务最大到期时刻。"""
    if not video_ids:
        return {}, {}
    up_map: dict[int, float] = {}
    cp_map: dict[int, float] = {}
    for chunk in _chunk_list(video_ids):
        placeholders = ",".join("?" for _ in chunk)
        up_sql = f"SELECT video_id, next_attempt_at FROM wechat_upload_retries WHERE video_id IN ({placeholders})"
        for r in _safe_query(conn, up_sql, chunk):
            ep = _parse_iso_or_epoch(r["next_attempt_at"])
            if ep and ep > up_map.get(r["video_id"], 0.0):
                up_map[r["video_id"]] = ep
        cp_sql = f"SELECT video_id, next_attempt_at FROM copywriter_deferred WHERE video_id IN ({placeholders})"
        for r in _safe_query(conn, cp_sql, chunk):
            ep = _parse_iso_or_epoch(r["next_attempt_at"])
            if ep and ep > cp_map.get(r["video_id"], 0.0):
                cp_map[r["video_id"]] = ep
    return up_map, cp_map


def _fetch_all_associated_maps(
    conn: sqlite3.Connection, video_ids: Sequence[int]
) -> tuple[
    dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]],
    dict[int, dict[str, Any]], dict[int, list[dict[str, Any]]],
    dict[int, dict[str, Any]], dict[int, list[dict[str, Any]]],
    dict[int, float], dict[int, float],
]:
    """统一批量汇聚全部关联表的映射快照字典。"""
    fe_map = _fetch_failure_events(conn, video_ids)
    ri_map = _fetch_recovery_items(conn, video_ids)
    sr_map = _fetch_subtitle_recoveries(conn, video_ids)
    dr_map = _fetch_delivery_recoveries(conn, video_ids)
    wp_map, sa_map = _fetch_wechat_publications(conn, video_ids)
    up_map, cp_map = _fetch_backoffs(conn, video_ids)
    return fe_map, ri_map, sr_map, dr_map, wp_map, sa_map, up_map, cp_map


def _extract_task_timestamps(
    d: dict[str, Any],
) -> tuple[str, str, Optional[str], Optional[float], Optional[float], Optional[float]]:
    """从行字典安全提取起止与失败时间文本及解析 Unix epoch。"""
    c_at = str(d.get("created_at") or "")
    u_at = str(d.get("updated_at") or "")
    f_at = d.get("failed_at")
    return (
        c_at, u_at, f_at,
        _parse_iso_or_epoch(c_at),
        _parse_iso_or_epoch(u_at),
        _parse_iso_or_epoch(f_at),
    )


def _row_to_task_facts(
    row: sqlite3.Row | dict[str, Any],
    fe_map: dict[int, list[dict[str, Any]]],
    ri_map: dict[int, list[dict[str, Any]]],
    sr_map: dict[int, dict[str, Any]],
    dr_map: dict[int, list[dict[str, Any]]],
    wp_map: dict[int, dict[str, Any]],
    sa_map: dict[int, list[dict[str, Any]]],
    up_map: dict[int, float],
    cp_map: dict[int, float],
) -> TaskUnitFacts:
    """将数据库行数据与关联表批量快照汇聚映射为 TaskUnitFacts 纯数据类。"""
    d = dict(row)
    vid = int(d["id"])
    c_at, u_at, f_at, c_ep, u_ep, f_ep = _extract_task_timestamps(d)
    return TaskUnitFacts(
        video_id=vid,
        youtube_id=str(d.get("youtube_id") or ""),
        slice_index=int(d.get("slice_index") or 0),
        parent_id=d.get("parent_id"),
        title=str(d.get("title") or ""),
        channel_id=str(d.get("channel_id") or ""),
        channel_name=str(d.get("channel_name") or d.get("channel_id") or ""),
        status=str(d.get("status") or "PENDING"),
        source=str(d.get("source") or ""),
        score=float(d.get("score") or 0.0),
        qualified_score_line=75,
        retry_count=int(d.get("retry_count") or 0),
        error_msg=str(d.get("error_msg") or ""),
        censor_tag=d.get("censor_tag"),
        bypass_censorship=bool(d.get("bypass_censorship")),
        preparation_ready=bool(d.get("preparation_ready")),
        source_subtitle_status=d.get("source_subtitle_status"),
        publication_review_required=bool(d.get("publication_review_required")),
        publication_wait_reason=d.get("publication_wait_reason"),
        created_at=c_at,
        updated_at=u_at,
        failed_at=f_at,
        created_epoch=c_ep,
        updated_epoch=u_ep,
        failed_epoch=f_ep,
        process_pid=d.get("process_pid"),
        failure_events=tuple(fe_map.get(vid, ())),
        recovery_items=tuple(ri_map.get(vid, ())),
        subtitle_recovery=sr_map.get(vid),
        delivery_recoveries=tuple(dr_map.get(vid, ())),
        upload_retry_next_epoch=up_map.get(vid),
        copywriter_next_epoch=cp_map.get(vid),
        wechat_publication=wp_map.get(vid),
        submission_attempts=tuple(sa_map.get(vid, ())),
    )


class FunnelDiagnosisDAL:
    """入库批次流程概览与异常诊断只读数据访问层 Mixin。"""

    def get_funnel_cohort_task_facts(
        self,
        window: Optional[str] = "today_bj",
        channel_id: Optional[str] = None,
        days: Optional[int] = None,
        since_time: Optional[str] = None,
        until_time: Optional[str] = None,
    ) -> list[TaskUnitFacts]:
        """按入库批次窗口与频道筛选主任务族，获取包含父任务与切片分集的事实快照。"""
        where_clause, params = _build_funnel_cohort_where(
            window=window, channel_id=channel_id, days=days,
            since_time=since_time, until_time=until_time,
        )
        with self.get_connection() as conn:
            _start_read_snapshot(conn)
            rows = _fetch_cohort_family_rows(conn, where_clause, params)
            if not rows:
                return []
            maps = _fetch_all_associated_maps(conn, [r["id"] for r in rows])
            return [_row_to_task_facts(r, *maps) for r in rows]

    def get_funnel_task_family_facts_by_ids(
        self, video_ids: Sequence[int]
    ) -> list[TaskUnitFacts]:
        """按指定任务 ID 列表查询其所属的主任务族全部事实。"""
        if not video_ids:
            return []
        with self.get_connection() as conn:
            _start_read_snapshot(conn)
            root_ids: list[int] = []
            for chunk in _chunk_list(video_ids):
                placeholders = ",".join("?" for _ in chunk)
                roots_sql = (
                    "SELECT DISTINCT COALESCE(parent_id, id) AS root_id "
                    f"FROM processed_videos WHERE id IN ({placeholders})"
                )
                root_rows = _safe_query(conn, roots_sql, tuple(chunk))
                root_ids.extend(r["root_id"] for r in root_rows if r["root_id"] is not None)
            root_ids = list(dict.fromkeys(root_ids))
            if not root_ids:
                return []
            rows: list[sqlite3.Row] = []
            for chunk in _chunk_list(root_ids, size=MAX_IN_VARS // 2):
                root_placeholders = ",".join("?" for _ in chunk)
                family_sql = (
                    "SELECT pv.*, COALESCE(rc.channel_name, pv.channel_id, '') AS channel_name "
                    "FROM processed_videos pv LEFT JOIN recommended_channels rc ON rc.channel_id = pv.channel_id "
                    f"WHERE pv.id IN ({root_placeholders}) OR pv.parent_id IN ({root_placeholders}) "
                    "ORDER BY COALESCE(pv.parent_id, pv.id) ASC, pv.slice_index ASC, pv.id ASC"
                )
                rows.extend(_safe_query(conn, family_sql, chunk + chunk))
            if not rows:
                return []
            maps = _fetch_all_associated_maps(conn, [r["id"] for r in rows])
            return [_row_to_task_facts(r, *maps) for r in rows]

    get_cohort_task_facts = get_funnel_cohort_task_facts
