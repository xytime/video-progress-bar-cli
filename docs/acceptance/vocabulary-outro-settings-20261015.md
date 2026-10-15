# 生词片尾配置验收记录

作者：Codex。2026-10-15（北京时间）。实现提交 `fe677a9`，基线 `a9691e0`。用户确认规格后开发；本记录明确区分隔离验收与生产采用。

## 已实现和验证

独立后台 `/vocabulary-outro-settings`：总开关、五类开关、频道条件、当前草稿匹配预览、逐任务冻结与最近执行记录；CAS 冲突和保存失败保留草稿。默认全部开启，类型规则与商品共用纯分类函数，运营配置独立。已生成、上传中、已发布和已冻结任务不受新保存影响。

全片零词时，对当前同一份 ASS 执行有界 Codex CLI 独立补提取；宿主验证同段英文完整词边界、同段中文连续子串。失败记录 FAILED 并阻止静默跳过；明确的无合适词结果必须绑定当前源视频、字幕摘要。配置关闭、失败或失效的旧片尾不可误选。独立英语世界学习卡不经过此渲染步骤，页面和实际任务预览明确说明适用范围，不更改其音频 QA 和内容时长。

- 首轮片尾、配置与共享分类单元测试 **42 passed**。
- 后台必需回归 **125 passed / 10 warnings**，覆盖首页、商品、采集规则、手动选品、新片尾页面；非本次新增的弃用警告保留。
- 包含生产现有改动的最终整合副本 **219 passed / 4 warnings**，覆盖片尾、补提取、既有词汇导出、商品、AGY、insight、部署与真实 Chromium。此次与前两轮有重叠，不累计为独立用例数。runner exit=0、OS 边界探针通过、沙箱清理完成。
- premium 严格静态检查 0 errors / 0 warnings；真实浏览器验证保存、重载、预览、冲突、故障保留、过期响应、键盘、390px 窄屏与三主题。桌面及手机截图已人工检查。

整合测试证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-junhyh6x`；源码清单 SHA-256 `1572dd011a9bd6db1b4bca6fbad30a0adf3fddf53f581d46ef7dfbc6bb761437`。首次后台回归：`video-pytest-obxp2fi4`。另有两次测试参数误指不存在文件，未执行用例；更正后上述整合测试通过，不将误调用计为验收。

## 问题视频本地验收

对 `a_SOXD8xc3M` 的 ASS 和已渲染视频创建本地副本，未改写生产素材和发布记录。原视频 223.862993 秒、66 个双语段；独立补提取得到 **28 个通过宿主对齐校验的词条**，追加 **10 页 / 30 秒**。成片 253.862993 秒，RENDERED、recovery_checked=true，valid_outro=true，输入/输出摘要绑定通过；已检查第一页实际图片。没有重新上传或发布。

证据及可播放成片：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/vocabulary-outro-acceptance-20261015/`。该目录保存 acceptance.json、恢复词条、派生 MP4、10 张片尾图和管理页三主题截图。

## 生产采用：尚未执行

已通过原生部署入口生成只读计划，target=`fe677a9`，使用上述已测整合副本，并选择保留当前关键词阶段配置。计划目录：`~/Library/Application Support/VideoProcessing/deployments/vocabulary-outro-20261015`。没有执行 apply，也没有进入维护、停服务、改生产源码、改搜索配置或重试投稿。

原生 `maintenance status` 当前为 RUNNING52、active=[]，但 safe=false：六个角色报告 LEGACY_WORKER，UI PID49660 与 ready-worker PID49987 同时报 UNREGISTERED_PROCESS。独立核实六个角色的真实启动标识仍匹配，启动时源码指纹均为 `d45c421ab70e9495eaf7fd36cfee3bbc5b5b6285091c725f33450bd456e03a84`，磁盘源码指纹为 `44db5fc4626992778ca8834195ef51f5e63b9bff9b8e821d664da4f2af2ad810`。

与上次完成部署的 expected_runtime 逐文件比较，**唯一漂移文件是生产现有未提交的 `src/config/settings.py`**，内容包含 AGY 默认模型/运行环境等改动，发生在本任务采用前。本次新增功能仍仅在独立工作区。不能把 active=[] 或测试通过当作维护来源门禁通过。

下一步须先对现有源码漂移及这两个存活进程完成受控恢复，使原生维护检查恢复一致，再重新生成有效部署计划并按正常九步采用。当前未强杀、删锁、伪造指纹或绕过检查；主干与原开发改动保留。后台生产入口尚未安装，不把只读计划称为上线。
