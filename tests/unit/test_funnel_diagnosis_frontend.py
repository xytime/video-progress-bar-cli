"""入库批次流程概览与异常诊断前端模块（模板挂载、静态资源规格与交互契约）单元测试。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.2.0 | 2026-10-29 | Antigravity | 新增方案 A 独立健康度视图导航 (/?view=health)、总览速览条与比例条/步骤胶囊规格测试。 |
| 1.1.0 | 2026-10-29 | Antigravity | 补充 _funnelDiagnosisRequestId 命名、--bg3 样式、动态 Tab 路由与空批次/零异常边界态契约测试。 |
| 1.0.0 | 2026-10-29 | Antigravity | 验证 index.html 挂载点与资源引入、funnel_diagnosis.js/css 行数与函数规范、filterState 保护及诊断契约。 |
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from video_processing.db.database import PipelineDB
from web import app as web_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def test_db(tmp_path: Path) -> PipelineDB:
    """创建全新隔离的 SQLite 数据库。"""
    return PipelineDB(db_path=str(tmp_path / "test_pipeline.db"))


@pytest.fixture
def mock_app_context(test_db: PipelineDB, tmp_path: Path):
    """隔离 app 中的 db 与 _OUT_DIR 依赖。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(web_app, "db", test_db), patch.object(web_app, "_OUT_DIR", out_dir):
        yield TestClient(web_app.app), out_dir


def test_index_html_template_mounts_and_assets():
    """验证 index.html 挂载容器、样式与脚本链接均准确声明。"""
    index_path = REPO_ROOT / "src" / "web" / "templates" / "index.html"
    assert index_path.exists(), "src/web/templates/index.html 必须存在"
    content = index_path.read_text(encoding="utf-8")

    # 1. 验证挂载点存在于 global-funnel-panel 内部
    assert 'id="global-funnel-panel"' in content, "必须存在 #global-funnel-panel 容器"
    assert 'id="funnel-diagnosis-mount"' in content, "必须存在 #funnel-diagnosis-mount 挂载点"
    assert content.index('id="global-funnel-panel"') < content.index('id="funnel-diagnosis-mount"'), \
        "#funnel-diagnosis-mount 必须挂载在 #global-funnel-panel 内部"

    # 2. 验证 CSS 与 JS 引入
    assert 'href="/static/css/funnel_diagnosis.css' in content, "必须引入 funnel_diagnosis.css"
    assert 'src="/static/js/funnel_diagnosis.js' in content, "必须引入 funnel_diagnosis.js"


def test_index_html_filter_state_protection():
    """验证 onFunnelCardClick 不再抹除非激活的 channel 与 search 筛选状态，且 fetchGlobalFunnel 并发触发 load。"""
    index_path = REPO_ROOT / "src" / "web" / "templates" / "index.html"
    content = index_path.read_text(encoding="utf-8")

    # 提取 onFunnelCardClick 函数体
    match = re.search(r"function onFunnelCardClick\s*\([^)]*\)\s*\{(.*?)\n  \}", content, re.DOTALL)
    assert match is not None, "必须存在 onFunnelCardClick 函数"
    fn_body = match.group(1)

    # 确保没有清空 channel 和 search
    assert "filterState.search=''" not in fn_body and 'filterState.search = ""' not in fn_body, \
        "onFunnelCardClick 不得重置 filterState.search"
    assert "filterState.channel=''" not in fn_body and 'filterState.channel = ""' not in fn_body, \
        "onFunnelCardClick 不得重置 filterState.channel"

    # 验证 fetchGlobalFunnel 传递了 channel 参数并在开始处触发 FunnelDiagnosis.load
    match_fetch = re.search(r"async function fetchGlobalFunnel\s*\([^)]*\)\s*\{(.*?)\n  \}", content, re.DOTALL)
    assert match_fetch is not None, "必须存在 fetchGlobalFunnel 函数"
    fetch_body = match_fetch.group(1)
    assert "FunnelDiagnosis.scope" in fetch_body, "漏斗与诊断必须共享可见范围"
    assert "channel" in fetch_body, "fetchGlobalFunnel 必须构造 channel 参数"
    assert "FunnelDiagnosis.load" in fetch_body, "fetchGlobalFunnel 必须并发触发 FunnelDiagnosis.load"


def test_funnel_diagnosis_css_specification():
    """验证 funnel_diagnosis.css 规格限制 (≤ 400 行、包含关键类选择器与主题变量)。"""
    css_path = REPO_ROOT / "src" / "web" / "static" / "css" / "funnel_diagnosis.css"
    assert css_path.exists(), "src/web/static/css/funnel_diagnosis.css 必须存在"
    lines = css_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) <= 400, f"funnel_diagnosis.css 行数不能超过 400 (当前: {len(lines)})"
    content = "\n".join(lines)

    # 验证 3 层选择器
    assert ".funnel-diagnosis-mount" in content
    assert ".funnel-diag-pills" in content
    assert ".funnel-diag-pill" in content
    assert ".funnel-diag-narrative" in content
    assert ".funnel-diag-cause-card" in content
    assert ".funnel-diag-drawer" in content
    assert ".funnel-diag-evidence-grid" in content

    # 验证 5 种边界态选择器
    assert ".funnel-diag-banner-error" in content
    assert ".funnel-diag-banner-stale" in content
    assert ".funnel-diag-banner-history" in content
    assert ".funnel-diag-banner-empty" in content

    # 验证项目主题 CSS 变量引用
    for var_name in ("--border", "--blue", "--red", "--yellow", "--green", "--text", "--bg2"):
        assert var_name in content, f"CSS 必须复用项目全局语义变量 {var_name}"


def test_funnel_diagnosis_js_specification_and_bounds():
    """验证 funnel_diagnosis.js 代码规格限制 (≤ 400 行、函数 ≤ 50 行、全局挂载与防抖)。"""
    js_path = REPO_ROOT / "src" / "web" / "static" / "js" / "funnel_diagnosis.js"
    assert js_path.exists(), "src/web/static/js/funnel_diagnosis.js 必须存在"
    raw = js_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    assert len(lines) <= 400, f"funnel_diagnosis.js 行数不能超过 400 (当前: {len(lines)})"

    # 函数最大行数检查 (≤ 50 行)
    fn_name = None
    fn_start = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("function ") or " = function" in line:
            if fn_name:
                span = i - fn_start
                assert span <= 50, f"函数 {fn_name} 长度为 {span} 行，超过 50 行限制！"
            fn_name = stripped.split("(")[0]
            fn_start = i
    if fn_name:
        span = len(lines) - fn_start
        assert span <= 50, f"函数 {fn_name} 长度为 {span} 行，超过 50 行限制！"

    # 验证对外接口与核心逻辑
    assert "window.FunnelDiagnosis =" in raw, "必须导出 window.FunnelDiagnosis"
    assert "_funnelDiagnosisRequestId" in raw, "必须存在请求世代计数器防止竞态"
    view = js_path.with_name("funnel_diagnosis_view.js").read_text(encoding="utf-8")
    assert len(view.splitlines()) <= 400
    assert "const esc =" in view
    assert "onclick=" not in raw + view, "动态数据必须通过委托事件读取"
    assert "onPillClick" in raw, "必须支持胶囊点击下钻"
    assert "onCauseClick" in raw, "必须支持原因点击下钻"
    assert "toggleTask" in raw, "必须支持任务展开证据抽屉"
    assert "openDetails" in raw and "/evidence" in raw, "必须按精确 ID 重新核实详情"
    assert "copyError" in raw, "必须提供错误摘要复制"
    assert "请手动选择错误文本" in raw, "剪贴板拒绝时提供可执行降级"


def test_frontend_data_contract_against_backend(mock_app_context, test_db: PipelineDB):
    """验证后端 API /api/funnel/diagnosis 输出结构能完整满足前端三层与边界态渲染需求。"""
    client, _ = mock_app_context
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with test_db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_FE', 'FrontEnd Channel', 'APPROVED')")
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (101, 'vid_fe_1', 0, NULL, 'Task FE 1', 'UC_FE', 'FAILED', 85, 'VISUAL_REVIEW_BUDGET_EXCEEDED', ?, ?)""",
            (now_utc, now_utc),
        )
        c.execute(
            "INSERT INTO publishing_failure_events (video_id, status, reason, failed_at) VALUES (101, 'FAILED', '测试失败', ?)",
            (now_utc,),
        )

    res = client.get("/api/funnel/diagnosis?window=today_bj&channel=UC_FE")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["channel_id"] == "UC_FE"
    assert data["channel_name"] == "FrontEnd Channel"
    assert "as_of_bj" in data

    # 验证 Layer 1 所需 summary 字段
    summary = data["summary"]
    for key in (
        "total_ingested", "affected_tasks", "unresolved_tasks", "stalled_tasks",
        "uncertain_delivery_tasks", "recovered_tasks", "diagnosis_sentence", "has_insufficient_history"
    ):
        assert key in summary, f"summary 缺少前端 Layer 1 必需字段: {key}"

    # 验证 Layer 2 所需 causes 列表字段
    assert len(data["causes"]) == 1
    cause = data["causes"][0]
    for key in (
        "cause_code", "cause_title", "category", "category_label", "affected_tasks",
        "unresolved_tasks", "longest_duration_seconds", "latest_progress",
        "recommended_next_step", "action_kind", "is_system_fault"
    ):
        assert key in cause, f"cause 缺少前端 Layer 2 必需字段: {key}"

    # 验证 Layer 3 所需 tasks 列表及三元组证据
    assert len(data["tasks"]) == 1
    task = data["tasks"][0]
    for key in (
        "video_id", "youtube_id", "slice_index", "title", "stage",
        "handling_state_label", "delivery_state", "unresolved",
        "facts", "inferences", "recommendations", "sanitized_error_excerpt"
    ):
        assert key in task, f"task 缺少前端 Layer 3 必需字段: {key}"


def test_frontend_boundary_states_contracts(mock_app_context, test_db: PipelineDB):
    """验证空批次与零异常整洁状态下诊断接口返回结构满足边界态渲染契约。"""
    client, _ = mock_app_context

    # 1. 空批次状态
    res_empty = client.get("/api/funnel/diagnosis?window=today_bj")
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    assert data_empty["success"] is True
    assert data_empty["summary"]["total_ingested"] == 0
    assert data_empty["summary"]["affected_tasks"] == 0
    assert len(data_empty["causes"]) == 0
    assert len(data_empty["tasks"]) == 0

    # 2. 存在正常流转任务（零异常整洁状态）
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with test_db.get_connection() as c:
        c.execute("INSERT INTO recommended_channels (channel_id, channel_name, status) VALUES ('UC_CLEAN', 'Clean Channel', 'APPROVED')")
        c.execute(
            """INSERT INTO processed_videos (id, youtube_id, slice_index, parent_id, title, channel_id, status, score, error_msg, created_at, updated_at)
               VALUES (201, 'vid_clean_1', 0, NULL, 'Clean Task', 'UC_CLEAN', 'PUBLISHED', 88, NULL, ?, ?)""",
            (now_utc, now_utc),
        )
    res_clean = client.get("/api/funnel/diagnosis?window=today_bj&channel=UC_CLEAN")
    assert res_clean.status_code == 200
    data_clean = res_clean.json()
    assert data_clean["success"] is True
    assert data_clean["summary"]["total_ingested"] == 1
    assert data_clean["summary"]["affected_tasks"] == 0
    assert data_clean["summary"]["unresolved_tasks"] == 0
    assert len(data_clean["causes"]) == 0
    assert len(data_clean["tasks"]) == 0


def test_navigation_and_workspace_health_view_integration():
    """验证左侧导航方案 A 独立子入口 (/?view=health)、工作区视图隔离与总览速览条声明。"""
    nav_path = REPO_ROOT / "src" / "web" / "static" / "js" / "console_navigation.js"
    assert nav_path.exists()
    nav_content = nav_path.read_text(encoding="utf-8")
    assert "/?view=health" in nav_content, "左侧导航必须包含健康度视图入口 /?view=health"
    assert "健康度：流程概览" in nav_content, "左侧导航子入口文本必须为 健康度：流程概览"

    ws_path = REPO_ROOT / "src" / "web" / "static" / "js" / "dashboard_workspace.js"
    assert ws_path.exists()
    ws_content = ws_path.read_text(encoding="utf-8")
    assert "health:'健康度：流程概览'" in ws_content or "health: '健康度：流程概览'" in ws_content, \
        "工作区标题字典必须注册 health 视图"
    assert "global-funnel-panel" in ws_content, "工作区控制必须联动 global-funnel-panel"
    assert "overview-health-strip" in ws_content, "工作总览页必须包含今日流程健康度速览条"

    diag_js = (REPO_ROOT / "src" / "web" / "static" / "js" / "funnel_diagnosis.js").read_text(encoding="utf-8")
    diag_js += (REPO_ROOT / "src/web/static/js/funnel_diagnosis_view.js").read_text(encoding="utf-8")
    assert "renderProportionBar" in diag_js, "诊断前端必须渲染互斥任务比例条"
    assert "renderTaskStepPills" in diag_js, "任务卡片必须渲染工序步骤进度胶囊"
    assert "funnel-diag-main-grid" in diag_js, "必须支持左根因右任务的 2 栏响应式布局"
