# 生词片尾配置验收记录

作者：Codex。2026-10-15（北京时间）。实现提交 `fe677a9`，基线 `a9691e0`。用户确认规格后开发；本记录明确区分隔离验收与生产采用。

## 已实现和验证

独立后台 `/vocabulary-outro-settings`：总开关、五类开关、频道条件、当前草稿匹配预览、逐任务冻结与最近执行记录；CAS 冲突和保存失败保留草稿。默认全部开启，类型规则与商品共用纯分类函数，运营配置独立。已生成、上传中、已发布和已冻结任务不受新保存影响。

全片零词时，对当前同一份 ASS 执行有界 Codex CLI 独立补提取；宿主验证同段英文完整词边界、同段中文连续子串。失败记录 FAILED 并阻止静默跳过；明确的无合适词结果必须绑定当前源视频、字幕摘要。配置关闭、失败或失效的旧片尾不可误选。独立英语世界学习卡不经过此渲染步骤，页面和实际任务预览明确说明适用范围，不更改其音频 QA 和内容时长。

- 首轮片尾、配置与共享分类单元测试 **42 passed**。
- 后台必需回归 **125 passed / 10 warnings**，覆盖首页、商品、采集规则、手动选品、新片尾页面；非本次新增的弃用警告保留。
- 包含生产现有改动的最终整合副本 **219 passed / 4 warnings**，覆盖片尾、补提取、既有词汇导出、商品、AGY、insight、部署与真实 Chromium。此次与前两轮有重叠，不累计为独立用例数。runner exit=0、OS 边界探针通过、沙箱清理完成。
- 生产随后出现视频号管理页回查改动；保留该源码及测试，重新整合后 **284 passed / 4 warnings**，新增投稿身份回查回归。最终 runner exit=0、探针通过、沙箱清理完成；不累计重叠用例。
- premium 严格静态检查 0 errors / 0 warnings；真实浏览器验证保存、重载、预览、冲突、故障保留、过期响应、键盘、390px 窄屏与三主题。桌面及手机截图已人工检查。

整合测试证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-junhyh6x`；源码清单 SHA-256 `1572dd011a9bd6db1b4bca6fbad30a0adf3fddf53f581d46ef7dfbc6bb761437`。首次后台回归：`video-pytest-obxp2fi4`。另有两次测试参数误指不存在文件，未执行用例；更正后上述整合测试通过，不将误调用计为验收。

上线采用的最终整合证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-mtg2v_k0`；源码清单 SHA-256 `d52e82553a48d9974af2446aaa493135a89005f3ca5e293c3bd39878cb0adb75`。

## 问题视频本地验收

对 `a_SOXD8xc3M` 的 ASS 和已渲染视频创建本地副本，未改写生产素材和发布记录。原视频 223.862993 秒、66 个双语段；独立补提取得到 **28 个通过宿主对齐校验的词条**，追加 **10 页 / 30 秒**。成片 253.862993 秒，RENDERED、recovery_checked=true，valid_outro=true，输入/输出摘要绑定通过；已检查第一页实际图片。没有重新上传或发布。

证据及可播放成片：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/vocabulary-outro-acceptance-20261015/`。该目录保存 acceptance.json、恢复词条、派生 MP4、10 张片尾图和管理页三主题截图。

## 生产采用：已完成

2026-10-15 15:05（北京时间）通过原生部署入口完成九步 `baseline → freeze → stop → backup → adopt → start → resume → restore → verify`，journal=`COMPLETE`、pending=null。部署 target=`80a8877`；目录 `~/Library/Application Support/VideoProcessing/deployments/vocabulary-outro-20261015-live`，部署 ID `0363370c00a943f9800555c5c7c4b128`。原先只读计划 `vocabulary-outro-20261015` 未执行，已被此新计划取代。

部署前发现的源码漂移已受控恢复。除原有 `src/config/settings.py` 代理改动，复核时又出现 `scripts/wechat_uploader.py` 管理回查改动。均先按摘要备份原文件，冻结入口后仅临时恢复与实际进程指纹完全匹配的已部署源码；原生 inspection.safe=true 后正常停机、备份数据库，再完整恢复原改动。未强杀、删锁或伪造指纹。恢复目录 `~/Library/Application Support/VideoProcessing/deployments/vocabulary-source-recovery-20261015` 保留逐步回执及原始文件。

生产原为 `DISCOVERY_ONLY`、自动准入开启；部署窗口使用现有 CAS 接口临时关闭，部署完成后恢复原值。采集规则、阶段配置、定时配置和配额计数保持不变，运行回读 `REFRESH_OR_ADMISSION`。生产原有未提交文件逐项摘要保留；唯一重叠的 settings.py 使用已测整合版本保存原改动。

线上页面 `http://localhost:9100/vocabulary-outro-settings` 返回 200；相同有效配置保存后重新读取，摘要与值一致。五类匹配与各类型关闭草稿预览均通过，未保存关闭草稿。总开关及五类开关仍全部开启。保存仅规范化 JSON 排版，不改变有效配置。

15:08 回读：维护状态 RUNNING；UI PID56417、ready-worker PID56855，六个角色归属与源码摘要一致，摘要 `0f67206a83836837c0c298e4119bb9dd5b4af196d0f8b849292ca54f3eec60e9`，无 LEGACY_WORKER/UNREGISTERED_PROCESS。正常 RUNNING 时未提供冻结来源回执，原生命令仍会显示 SOURCES_NOT_VERIFIED/safe=false；不将它误解成部署失败或维护可停机。

线上证据：上述本地验收目录中的 `production-readback.json` 与 `production-runtime.json`。目前完成代码、隔离验收、运行采用和后台回读；下一条自然视频的实际片尾仍待自然产出，未为验收重新处理、上传或发布历史视频。
