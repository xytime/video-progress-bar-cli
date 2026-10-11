# 关键词追踪 / 专题候选 v0.2 隔离验收

责任记录：Codex；用户于 2026-10-11 确认 v0.2，验收于 2026-10-12（北京时间）完成。模型版本未单独核实。

**结论：确认范围已实现，隔离验收通过；生产搜索未开放。** 工作仅在独立工作区与沙盒测试根进行，没有改生产配置、重启后台或进行真实 API 搜索。收藏只保存选题意向，候选不会进入制作/发布流水线。

确认依据：[唯一规格 v0.2](../../specs/topic-keyword-tracking-architecture.md)。分支 `codex/topic-candidate-workbench`，开发基线 `eb7b7fa34237c549bcc348c562de024d205c16dd`，实现提交 `46b4081`（后续提交仅补交付记录）。本报告属于隔离交付；生产运行采用、真实配额与真实响应仍待后续开放阶段核实。

## 已交付行为

- 后台新增“关键词追踪”入口与独立 `/topic-candidates` 页面。专题新建/编辑、暂停/恢复/归档、到期管理；最多 10 个有效专题，默认最近 7 天与 7 天有效期。
- 手动官方搜索与批量详情，每轮一页最多 25 条；全局单作业、幂等复用、15 分钟冷却。预算按逻辑项目、桶与太平洋日期持久化，默认每天搜索 20 次、详情 40 units，临时详情失败最多重试一次。
- 源 ID 跨专题去重，候选筛选/分页/原链接/收藏/取消/排除，收藏绑定内容与规则版本；统计变化不使收藏失效，排除不会随重新发现复活。
- 真实时长、直播/预告、缺资料、现有 P0/频道规则、黑名单与主库已有记录检查；异常阻挡收藏。两个状态维度分开展示，未知统计/语言如实提示。
- 宿主保护、请求总超时 20 秒/作业 60 秒、暂停/OFF 阻挡后续请求、停止状态与重启恢复；预算不因失败或重启清零。
- 真实回环对端、Host/Origin、本机会话、CSRF、CAS；数据库短事务和两秒写锁上限，整理决定与审计原子提交。API 字段到期本地删除，即使 OFF 或重启也不自动联网刷新。
- 桌面和 390px 窄屏、已有明暗/高对比/字号偏好、键盘及失败后保留草稿。无 AI、定时搜索、Bot 写入、下载、准入、制作或发布入口。

配置新增 `topic_search_enabled=false`、`topic_quota_verified=false`；`.env.example` 同样默认关闭。运行模式初始化为 OFF。测试中的开放配置、API 凭据和结果均为隔离夹具，不是生产配置或真实服务回读。

## 实际验收证据

| 验收批次 | 结果 | 证据与适用范围 |
| --- | --- | --- |
| 最终专项与既有控制面 | **113 passed，0 failed/0 skipped，2 warnings** | [专项回执](evidence/final/receipt.json)、[日志](evidence/final/pytest.log)。包含四个专题单元/API/异常/适配器文件、专题真实 Chromium 浏览器用例与旧控制面安全用例；产品源码为最终实现 |
| 全部现有浏览器与 Dashboard 交互 | **297 passed，0 failed/0 skipped** | [回执](evidence/browser-regression/receipt.json)、[日志](evidence/browser-regression/pytest.log)。较早源码快照，之后的专题错误处理和新增用例由最终专项重验；不将两批计数相加 |
| 受影响原有单元/API | **93 passed，0 failed/0 skipped，5 warnings** | [回执](evidence/existing-regression/receipt.json)、[日志](evidence/existing-regression/pytest.log)。切片、频道漏斗、Dashboard/API、控制面、频道策略、规则热加载和视频筛选；既有业务实现未改 |
| 操作系统隔离探针 | **全部拒绝成功** | 各批 [boundary-probe.log](evidence/final/boundary-probe.log)：沙盒外读取、写入、网络、信号、卷别名和子进程越界写入被拒绝；探针退出码 0 |
| 源码绑定 | **最终产品代码、样例配置与专项测试逐项 SHA256 一致** | [交付源码绑定](evidence/tested-files.json)；保留各批完整 source-manifest.json 和其回执摘要；设计文档在工作区独立 lint/审计并记录 hash，未冒充 runner 快照内容 |
| 设计与静态 UI | **设计 lint 0 errors/0 warnings；新专题 UI 无新增严格检查问题** | [设计 lint](evidence/design-lint.json)、[当前严格检查](evidence/ui-audit.json)、[原基线严格检查](evidence/ui-audit-baseline.json) |

最终批次使用 Chromium 148.0.7778.96 / revision 1223，实际浏览器与 FastAPI、临时真实 SQLite 联动。YouTube 响应由内存适配器或 httpx.MockTransport 提供，未发真实网络请求；SQL、唯一键、回滚、锁与预算均使用真实临时 SQLite。跨进程测试使用沙盒内子进程。

两条最终 warnings 来自原后台的 FastAPI `on_event` 弃用提示。隔离探针日志还保留既有 `.pth` 启动诊断；探针实际结果及 pytest 均成功。原始日志逐字归档，保留 pytest 自带的尾部空白，由证据目录局部 Git 属性排除空白检查。静态 UI 严格检查整项目仍返回 exit 1：原 `index.html` 的两条 actionless-button 报告在基线中已存在，本次只因增加导航而行号 +1，未宣称整项目零问题。未扩大本次范围重做旧页面。

## A01–A21 对照

以下“通过”均指隔离范围；外部服务/生产部分列在下一节，不混入通过结论。测试函数名中的 A 编号可直接定位用例。

| ID | 隔离观察结果 | 主要证据 |
| --- | --- | --- |
| A01 | 创建、编辑、刷新、服务重建后保留；创建/GET 无搜索请求 | `test_a01_*` 单元/API；浏览器完整流程 |
| A02 | 空白/超长/非法日期、Unicode 重复、第 11 个有效专题及恢复超容量拒绝；无半成品审计 | `test_a02_*`；键盘表单验证/草稿保留 |
| A03 | 一页 25 条，确切源 ID/字段/原链接、结果计数正确；工作线程延迟不改变本轮查询时间边界 | `test_a03_*`；适配器参数断言；桌面截图 |
| A04 | 成功零结果与失败分开；失败保留旧候选且不提示虚假零结果 | `test_a04_*` 单元/浏览器；空结果截图 |
| A05 | 跨专题一个候选、多命中关系；已有父视频/切片状态可见，禁止收藏且不改主库 | `test_a05_dedup_across_topics_and_existing_slices` |
| A06 | 收藏/统计变化保留，标题和规则变化需重核；没有制作动作 | `test_a06_saved_stats_and_content_versions`；浏览器收藏刷新 |
| A07 | 归档再发现仍排除；拒绝恢复排除 | `test_a07_rejected_survives_archive_and_rediscovery`；窄屏排除截图 |
| A08 | 179/180/1800/1801 秒边界、直播/预告/不可用/资料缺失准确阻挡；未知统计和语言不造值 | `test_a08_*` |
| A09 | 真实现有 P0/频道规则、黑名单、规则/DAL 失败阻挡收藏；既有规则不变 | `test_a09_*`；当前规则包实调用 |
| A10 | 幂等复用、跨进程内核锁不能被恢复抢走、线程/进程抢最后预算不超额 | `test_a10_*` |
| A11 | 保守预留、详情最多一次重试、重启不清预算、PT 日界与夏令时 | `test_a11_*`；作业和预算 DAL 回读 |
| A12 | 默认关闭、额度未核实/无项目/无 API/预算不足阻挡；官方凭据、限流、配额错误区分 | `test_a12_*`；适配器错误码用例；关闭状态截图 |
| A13 | 保护关闭/未知/窗口进入即阻挡下一请求；窗口缩短请求截止；总请求超时有界；数据库忙后停止记录在 5 秒内完成 | `test_a13_*`；`test_total_deadline_and_missing_credentials` |
| A14 | 搜索中暂停/归档/OFF 显示 STOPPING，后续请求零新增；孤儿作业转 INTERRUPTED，无恢复补跑 | `test_a13_a14_*`、`test_a14_*` |
| A15 | 回环、会话/过期、CSRF、Origin/Host、旧版本拒绝；不信任转发头；伪造局域网对端拒绝 | `test_a15_*`；实际路由请求，非真实局域网连通测试 |
| A16 | HTML/脚本/指令标题和描述只作为文本；外链由源 ID 固定构造，无授权或脚本执行 | `test_a16_untrusted_text_and_off_page`；关闭状态截图 |
| A17 | 无分数/准入/加工/发布写入口；主表无专题新增；依赖与 DAL 写语句检查通过 | `test_a17_*`；实际 404/422 与主库回读 |
| A18 | 决定/审计和整批结果各自全提交或全回滚；并发旧版本 409；SQLite 忙返回有界错误 | `test_a18_*`；真实锁、事务、触发器故障 |
| A19 | 30 天/OFF/启动清理源字段，保留 hash 与排除决定；不联网；关闭连接后数据库页不含测试标题 | `test_a19_*`；不宣称清除外部备份或其他读者持有的旧 WAL 快照 |
| A20 | 桌面/390px 完整任务、键盘、错误草稿、筛选 URL/分页、复制降级、主题和字号可用 | 全部专题浏览器用例；下方 8 张真实截图 |
| A21 | OFF 不影响旧队列；专题初始化忙不阻断原路由；逐字 hash 校验的 eb7b7fa 原 DAL 能操作带新表的库，候选/排除保留 | `test_a21_*`、93 项旧回归、297 项全浏览器回归 |

## 可检查界面

[桌面收藏](evidence/screenshots/desktop-saved.png) · [390px 排除](evidence/screenshots/narrow-rejected.png) · [草稿恢复](evidence/screenshots/recovered-draft.png) · [关闭搜索与不可信文本](evidence/screenshots/closed-search-untrusted-text.png) · [成功零结果](evidence/screenshots/empty-search.png) · [暗色](evidence/screenshots/theme-dark.png) · [亮色](evidence/screenshots/theme-light.png) · [高对比](evidence/screenshots/theme-contrast.png)。截图均为沙盒夹具，不是生产候选或生产搜索开放证据。

## 复验方式

遵守项目隔离 runner，不在生产工作区裸跑 pytest。独立工作区复验命令（本次借用已安装 venv 作为解释器，不运行其生产代码）：

```sh
/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/unit/test_topic_candidates.py tests/unit/test_topic_candidates_api.py tests/unit/test_topic_candidates_edges.py tests/unit/test_topic_search_adapter.py tests/browser/test_topic_candidates_browser.py tests/unit/test_dashboard_control_plane_security.py
```

其余两批的完整参数与时间见相应 receipt.json。没有媒体处理变更，本轮不进行渲染/上传/发布验证。

## 尚未开放的生产阶段

1. 核实实际 Cloud 项目、桶额度、共享调用者和可分配预算，以及已启用的宿主保护；确认采用路径/代码版本、本机访问与到期清理。当前只能证明本模块预算约束，不能证明全项目配额预留。
2. 用户另行允许开放后，在原生产工作区空闲时安排采用；受限试运行最多 3 个专题、合计 3 次真实搜索，核对实际源字段、预算、暂停/关闭与主流水线无本功能创建任务，再做用户流程验收。

本轮没有合入生产 checkout 或切换其分支，不因隔离通过而打开 `.env` 开关。后续代码采用后仍应保持 `TOPIC_SEARCH_ENABLED=false`、`TOPIC_QUOTA_VERIFIED=false` 和 OFF，直至该阶段获得明确授权。

回退顺序：本机页面先关闭搜索，观察本模块终止后关闭宿主搜索开关，再回退本模块代码；保留候选增量表、决定和审计，不删库、不动旧任务、不补跑。在途请求不能瞬间撤销；持续数据库故障时停止记录无法落盘，内核锁在有界尝试后释放，待数据库恢复后本地维护将孤儿作业标为 INTERRUPTED。隔离回退已验证，实际生产回退操作仍未执行。

本轮按 codereview 方法对最终相关改动做自检，未发现剩余阻断问题；这是本轮自检，未冒充独立评审或生产验收。
