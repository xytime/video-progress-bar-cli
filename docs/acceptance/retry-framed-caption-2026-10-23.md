# 单片独立字幕区上线与重发验收

日期：2026-10-23（北京时间）；执行：Codex（具体模型版本未知）。

用户已确认 [单片版式规格](../specs/retry-blocked-caption-layout-2026-10-23.md)，并授权验证、上线、重发失败视频。精确对象为 `i1WsMclsgOs:0`；`zUv-6-FPQfw` 是另一条视频，未另外重置。

## 实现与完整成片

修复提交 `7e8856fb3bfb178869d4fa64137bd1dc8e02342a`，已采用到生产 `main` 并推送 `origin/main`。

- 仅原片名与 SHA-256 同时匹配时采用 `i1WsMclsgOs-framed-v1`；原片更换、缺段、缺译文、TTS 或版面溢出均停止。其它视频沿用 A/B 规则。
- 原片完整等比缩为 675×1200，放在 1080×1920 画布的 `(202,120)`；双语区为 `1350–1700`，保留全部 42 段内容及时间。原声直接复制，不新增配音。
- 逐帧解码全部 4,061 帧；字幕最下沿为 1617；画面区域与原片逐帧比较，最低 PSNR 为 34.5657；画面与字幕之外仅有编码容差内的黑色背景。检查首尾、169、173、1317（最长字幕）、3126 帧。
- 输出 H.264、yuv420p、1080×1920、30 fps，容器时长 135.418776 秒；音频压缩数据与原片一致。字幕与时间完整性由真实 42 段夹具回归验证。
- 原片 SHA-256：`8cca6dba707efd8b7de8410ebe93ad4c52b2ab7ee249cfdb94eae88b79b70a9e`。
- 预验收与正式流水线输出 SHA-256 均为 `08b4aaf35843e905e1f98217f97c95fda478fd5f350042bf3e18393cf12260e2`；生产回执模式为 `FRAMED`，绑定原片、ASS、版式计划与实现哈希。

完整渲染及逐帧证据：`/Volumes/EXT2T/AppDataOffload/ryusei/retry-framed-render-20261023/`，含 `qa.json`、验证程序、成片及审阅 PNG。

## 隔离回归

独立修复版本通过 68 项。将生产现有 dirty/untracked 维护源码复制到独立物理目录，再叠加本次六个已提交文件，组合回归通过 **270 项**，16 条既有依赖弃用警告；浏览器和 OS 隔离探针均退出 0。

组合证据：`/Volumes/EXT2T/AppDataOffload/ryusei/TestRuns/video-pytest-vfv_jmin/`。源码清单 SHA-256：`2f9b0600d580ec44c484f45480f61e9259fae1e505ee4f0df4f109bb06c04e33`。覆盖审核批准与技术失败区分、断点复用、真实翻译完整性、A/B 反例、精确单片 FRAMED、溢出/失配阻断、浏览器状态和发布防重传。临时组合工作区已清理，验收证据保留。

## 运行采用

原生部署事务 `e06a5ceb31b84a4d897e99c12bfe93b6` 九步完成，最终 `COMPLETE`。

- 冻结后 stop 首次在动作前被 `MAINTENANCE_INSPECTION_REJECTED` 拦截，未停止或采用源码。重查为 `safe=true / IDLE / active=[] / unknown=[]`；核对事务仅完成 baseline/freeze、没有 stop owner 回执，并在项目部署锁内重新执行原生 preflight、stop、verify。之后原生 recover 识别 stop 已完成并继续；未改写事务日志、强杀或强解锁。
- 一致性备份、源码采用、维护启动、恢复调度、最终回读均有原生回执。原有未提交工作和关键词阶段配置保留。
- 新 UI PID **85987**，birth `1792749191.145982`，实际 cwd 为 EXT2T 主工作区，监听 **9100**。
- 采用/启动源码 SHA-256：`3d8a7bb073eebb542c1047d11f84ce552389198827bac9e475126d4cd7680717`。
- 最终回读为 `RUNNING / IDLE`。

部署证据：`/Users/ryusei/Library/Application Support/VideoProcessing/deployments/retry-framed-20261023/`，含计划、原文件备份、数据库备份、步骤回执和精确任务回读。

## 正式重试与剩余发布状态

17:54 前用只读 SQLite 一致性快照确认目标为 `FAILED`、无 PID，微信与抖音账本均无提交记录。只调用一次 `/api/videos/i1WsMclsgOs/retry`，返回 `success=true / triggered=true`。

17:54 正式流水线完成字幕处理：进度回执为 `COMPLETE`，`reused_steps=[asr,copy,translation]`；生产成片与已验收成片哈希相同。人工 P0 放行已被本轮日志确认；不再因旧政治标签重复要求人工放行。

17:55:57 进入 `AI_COVER_PENDING`，专属封面任务为 `i1WsMclsgOs-5ccfc6049e52`。初始 AGY 认证缓存为 `AUTH_REQUIRED`，后台未主动打开授权页。随后真实的无浏览器认证检查通过；在原生协调器互斥中，仅为目标运行既有 AGY 执行器，18:06:01 真实生成超时 `PROCESS_TIMEOUT: budget=125s`，无可用图片。

原生巡检器在 18:06:08 按已有规则创建 `agy_failed` 的 Luna 交接；未伪造失败、调整截止时间、供应商或预算。Luna 在 18:06:59 完成生图与独立看图复核，`decision=PASS`；18:07:03 项目封面渲染器完成专属封面，来源 `codex_luna_ai_visual`，未采用本地固定背景。本轮已查看并检查最终封面。

- 真实底图：1086×1448，SHA-256 `d8383e953b33bc25a4c6782d3234a6f4c6b5d6a170f3746c3d20129680fab608`。
- 最终封面 SHA-256 `280844cb31549c90af6fec26fc7c647b6e1041fadb81cf082df9a6a068bbbff0`。
- 完成物和独立复核证据：生产目录 `ai-cover-finish/i1WsMclsgOs-5ccfc6049e52/`。
- 数据库原子变更为 `PENDING / preparation_ready=1`。既有二创队列自动创建 pair 19；二创 B 策划失败按自身规则等待，不阻塞普通 A 成片，也未被本轮重置。

18:08 提交前的一致性快照确认微信、抖音账本为空，既有 A/B 等待记录无 attempt、原生 ID 或提交意图。仅调用一次 `/api/videos/i1WsMclsgOs/process` 继续既有待发布任务，接口成功接纳；上传器在打开浏览器前退出 11，保留 `PENDING / preparation_ready=1`。未再次调用重试接口，未清除检查点。

进一步只读回读确认：真实浏览器锁未被占用、普通本地冷却已结束；拦截来自账户统一调度的 **过去 24 小时 55 次访问已超过 20 次上限**。原生审计事件 `DEFERRED` 明确记录“全账号过去24小时访问额度已用完，最早 1792788840”，即北京时间 **2026-10-24 04:54:00**。当前业务错误文案把这类准入等待统一显示为“同账号浏览器会话占用”，不能据此认定真实浏览器在途或再次字幕失败。

截至 18:09:48，目标无提交意图、原生 ID、平台受理或公开可见证据。已就“等待额度恢复”与“仅该片跳过一次本地额度”向用户明确询问；未经答复不签发跳过凭据、不更改账户政策或调度。额度恢复时间仅指本地资格，不承诺具体上传完成时间。

上述封面和访问额度等待不影响文案、ASR、翻译与已完成成片的有效检查点。追加证据为部署目录的 `before-ready-process.json`、`ready-process-response.json`、`retry-latest.json`、`publication-admission.json`，以及生产 `output/wechat_evidence/i1WsMclsgOs/1792750082001056000/uploader_stdio.log`（退出 11）。
