# 整改候选独立审查

审查者：Codex。开发执行：Antigravity。用户已授权审查通过后的上线。

## 候选 1：REQUEST_CHANGES

- 提交：`548a243beaadb0203519b559bdee63cd5120dae3`。
- 此提交不获上线、生产会话替换或重启放行。
- 已向正在执行的 Antigravity CLI 会话发送具体整改要求，继续开发。

### 阻断项

1. `wechat_uploader._wait_and_save_login` 仍仅等待 URL，未验证发布控件、未验证独立新上下文复用就更新授权并通知；原子保存失败回退直接覆盖旧 state。`_stamp_login_success` 元数据失败仍回退更新 legacy marker。失败被写成成功。
2. `wechat_auth_state.evaluate_wechat_session_status` 对缺失验证、陈旧验证和 `INVALID_ORIGIN` 可返回绿色；无授权 marker 但已验证会话被武断判断未授权；网络超时被无依据描述为不影响会话。
3. 元数据路径将 `wechat.json` 和 `wechat_state.json` 映射到同名文件，身份只记录 basename；任意自定义 state 会继承/改写同目录生产 marker/flags。原子 replace 未保护读改写并发。授权事件伪造保活时间。
4. 失败记录含原始异常/完整 URL 的自由文本，读取未验证时间戳范围或记录身份。只截断字符串不构成凭证脱敏。
5. 保活来源只检查 hostname，控件接受泛化 file input/发表按钮；跳转后及保存前没有重新核验官方 HTTPS 源和发布页，可能保存失效/错误页面。失败分类不准确。
6. 报告未覆盖实际调度开关、下次检查、自动尝试及锁等待；错误来源浏览器测试允许 `NETWORK_TIMEOUT` 替代，证据不足。

### 下一验收阶段

先修正并提交精确候选、差异与测试回执，由 Codex 重新独立审查。代码通过后可签发明确范围的真实会话验证放行；真实平台验证及独立复用通过后，才签发生产采用放行。上线前再次检查流水线空闲，保护主目录其他任务的未提交改动，最后核实新进程与实际运行结果。

## 候选 3：代码 PASS；仅放行受锁保护的真实登录验收

- 冻结提交：`3054114c91c636fd5833c693c13bd82f015016d3`，基线 `aa58c8068951d6ec941d63334b55a7b042ae4ae0`。
- Codex 独立单元回执 `/private/tmp/video-pytest-067ltdwu`：159 passed、20 subtests passed、2 warnings；边界探针与 pytest 均退出 0。
- Codex 独立浏览器回执 `/private/tmp/video-pytest-0fvnvevu`：18 passed；新增管理页 case 因测试 Cookie 格式无效失败，修正为标准空白状态后在 `/private/tmp/video-pytest-yc2i9ey0` 独立补验 1 passed、7 deselected。合计 19 个浏览器场景通过，分别绑定回执，不声称单次全通过。
- 八个业务文件与 067ltdwu 成功快照逐字一致：uploader、keepalive、独立 verifier、bot formatter/telegram_bot、auth_state/page_contract、web app。最后变更只修正管理页测试状态构造。
- 已核查旧失败不报绿、严格官方来源与发布控件、状态身份和原子写入、授权后新上下文复用、过期 flag 文案、管理页 DOM 异常失败，以及 29 秒迟到允许后及时检查。
- 仅放行 Antigravity 使用已审候选执行有界真实验收：生产规范 state 路径的 WeChatSessionLock、旧会话只读验证、空白自定义会话桌面快捷授权、实际授权元数据及独立新上下文复用。执行脚本本身须经 Codex 核查正确的生产路径、失败非零返回、已启用桌面开关与脱敏输出。
- 仍未放行合入主干、推送、生产凭据替换或服务重启；真实验收通过后另记生产 PASS。禁止视频上传、评论/联系人消息、强制修改阈值、历史续投或改写 Codex 审查结论。
- 11:41 生产仍有 1 个 TRANSCRIBING/FFmpeg 任务；上线前必须重新确认空闲，保留主干其他任务提交及 topic_clues 未跟踪工作。回滚使用明确集成提交的 revert，禁止 reset --hard。

### 真实验收执行脚本范围 PASS

- Codex 2026-09-28 12:03 BJ 读审 `/private/tmp/verify_wechat_auth_live_candidate.py`，SHA256 `58bcde1c97cb7595191ef04009f02efbb148be3e9205a58a04aedd5578b9445d`。
- 明确生产路径、锁内基线与 finally 指纹比对、独立空白 state、启用桌面授权开关、失败非零、禁用 Telegram 环境变量、独立复用返回字典及原始子进程日志不外发。
- 子进程独立进程组，120 秒超时 TERM，随后 KILL 自己进程组并回收。仅授权 Antigravity 执行该冻结脚本一次；生产合入、会话替换和重启仍待真实结果后的生产 PASS。

### 真实运行阻断，生产采用仍为 REQUEST_CHANGES

- 自然生产调度于 12:12 触发 `--login-only --relogin`，12:13:57 桌面 watcher 终态 `ACCESSIBILITY_DENIED`，随后等待扫码。Codex 同宿主只读预检及子进程 `start_new_session=False/True` 均返回 READY；后台权限归属尚需解决。
- 12:17 Codex 独立执行 Antigravity 的脱敏诊断脚本（SHA256 `ea32e6660094e5d2e701d3d2ff5cc912b0ffab9d2d2df3faded0b04cda189a05`）：网页快捷按钮已点击，桌面 watcher `CLICKED_VISUAL`，网页资料允许未点击，发布控件未验证，实际授权时间为空，尝试 FAILED/PAGE_UNREADY，uploader 退出 2。生产 state/marker/flags 锁内指纹一致。
- 回执位于候选 ignored output：`auth_diagnostic_receipt_1790569065.json`。这证明桌面点击和网页授权完成是不同事实；不能把 READY 或 CLICKED_VISUAL 报为授权成功。
- 12:20 生产旧 state 的独立新上下文验证返回官方源正确、LOGIN_REQUIRED、正向控件未验证，`success=false`；回执 `codex_production_readonly_20260928.json`。旧凭证文件保留，但当前会话不可用，不得报告正常或完成。
- 按用户完整修复上线授权，Codex 仅受控结束已失败且等待扫码的 login-only PID 47748 及其子树（6 个进程，全部退出）；未中止上传/发布或生产服务，未修改生产凭证和标记。
- 队列 API active=0 不充分：独立 ready worker 曾持发布优先租约。其发布子进程退出、`read_lease_owner(...)={}` 才作为实际空闲证据；不得凭残留锁文件或常驻 worker PID 推断占用，更不得删除活跃锁。
- 下一步只在诊断包装中读取网页来源/路由布尔、固定授权文案及允许元素角色/标签，定位 CLICKED_VISUAL 后的网页阶段，再交最小修复和真实复用证据。未授予生产集成、推送、会话替换或服务重启 PASS。
- 12:27–12:28 Codex 从已授权宿主独立运行绑定 parent `7c4f20b7988465509f2715d898c711baed90fa59212c2175f6427c9917cd3083` / wrapper `99dc62eead35deeefb2cdba4f076c70fa53b6661170b8b59a894457456cb17d3`：桌面 CLICKED_VISUAL，官方 CREATE 路由，但发布强控件仍缺失；可信 frame 共 2，固定资料授权文案和允许元素均未出现。回执 `auth_diagnostic_receipt_1790569626.json`，实际授权未生成，退出 2；不能归因为 HOME/LIST 路由或允许按钮 role 不匹配。
- 12:34 Codex 用一次性 `launchctl submit` 临时任务执行同一候选 `.venv` Python 的只读 desktop preflight，结果 ACCESSIBILITY_DENIED；随后移除本次临时任务退出 0。直接宿主 READY 与 launchd 拒绝构成真实启动链差异。生产 UI plist 使用 pyenv Python，经 launchd 启动；不得凭改用 `.venv` 路径或重启推定权限恢复，也不得写 TCC 数据库绕过授权。
- 12:37 白名单结构回执 `auth_diagnostic_receipt_1790570219.json` 证实具体判据遗漏：官方 CREATE 主页面 complete，上传容器可见，“选择视频”可见，顶层 file input 为 0；官方同源子 iframe complete，含 1 个视频 file input。原探针仅检查顶层 input/“上传视频”，因此实际页面就绪仍被判 PAGE_UNREADY。Antigravity 已获最小判据修复工单，不允许据此跳过独立复用。
- 12:46 Codex 从系统设置只读观察到现有 `python3.12` 辅助功能关闭；已确认生产 LaunchAgent 与项目 `.venv` 最终解析到同一 `/Users/ryusei/.pyenv/versions/3.12.4/bin/python3.12`。该权限将新增解释器级界面访问能力，已向用户发起操作前明确确认；未获答前不更改设置。
- 首发帖只读 DAL 快照：最近可评论 publication 1245（`edH4S6JYB7c`）账本 COMMENTED、attempt_count=3；近 3 天待处理互动为空。这是账本证据，尚未以本轮恢复后的生产会话完成平台回读，不能据此宣称两个功能均验收完成。

## 新版发布页识别候选：代码通过，真实独立复用仍阻断

- 功能提交 `6df3aa7ecdbbec0f7e36f9cf34dfc78127bb2f4f` 支持官方同源子 iframe 视频输入、精确唯一可见上传控件；拒绝外域、隐藏/重复控件、非上传区域、DOM 异常及超界候选。子 frame 在执行探针后再次核验来源。
- Codex 独立相关回归 `/private/tmp/video-pytest-gp1ml36h`：70 passed，1 failed；唯一失败为旧 keepalive Mock 未建模新增定位接口，count() 为 MagicMock 导致 TypeError。测试修正提交 `6e6aaf34b634ce851fbe8bae1ee25b4e5e821e92` 保留原 PAGE_UNREADY 断言；独立单项补验 `/private/tmp/video-pytest-8jz1aqf2`：1 passed、退出 0。八个业务源与前一回归快照逐字一致，修正测试与成功补验快照逐字一致，不声称单次 71 全通过。
- 本次真实验收冻结 parent SHA256 `ef66ad30ec2ab9b526f5998723411c74601f75dc2324ca082e327e04f3c3f4d3`，wrapper SHA256 `0344d1f77ce21f4263a8de0820666206b0698095682bdbfda98a062a8b53c74d`，绑定 receipt `auth_diagnostic_receipt_1790571906.json`。
- 13:05 BJ 的实际尝试（receipt 时间为准）：preflight READY、桌面 CLICKED_VISUAL、快捷授权正向判断成功；官方 CREATE、发布控件 true。但保存阶段新上下文复用仍失败，子进程退出 1、last_auth_attempt_status=FAILED/PAGE_UNREADY、authorized_at=0。生产 state/marker/flags 指纹一致。
- 此结果只证明新版页面识别故障已跨过，不能报告保存或授权闭环成功。继续定位初始 context 与复用 context 的差异，禁止削弱独立复用门禁；生产采用继续 REQUEST_CHANGES，尚未集成、push 或重启。
- 13:12 后自然 login-only PID 79996（UI 95170 子进程）进入 QR_FALLBACK，桌面结果 NOT_STARTED；不能将此轮说成 ACCESSIBILITY_DENIED。Codex 核实精确参数和本次扫码文件后，仅结束该登录子树（6 个进程，后续全部退出），未信号 UI/Bot/发布服务。
- 现有首评 receipt 的更精确读审：2026-09-28 05:37 BJ、verify_only=true、status=COMMENTED、完整作者正文回读匹配、作者评论 1 条，绑定方式 unique_exact_published_description，存在 final.png。此为今天已有平台只读回查证据；仍待恢复后本轮回查。
- 新诊断执行请求因额外 opaque 会话副本被宿主自动审批拒绝；未执行。已要求删除全部额外复制与凭据留存，只使用原业务临时 state 生命周期及页面/UA 固定分类观测，再审查执行。
- 安全替代 wrapper SHA256 `11b6033a6043db0d2274496688b6f90b49a7cb531aef77f2dc4f637933abe719` 通过审查：原保存函数原样执行，仅在 storage_state 和 reuse context.close 边界读取白名单结构，不额外复制凭据。首轮锁忙未启动授权；实际租约释放后再次执行，receipt `auth_diagnostic_receipt_1790572821.json`，退出 1，生产指纹一致。
- 该回执精确定位复用差异：初始官方 CREATE、视频控件 true、UA CHROME_124、window.chrome=true；复用官方 HOME、无登录提示、视频控件 false、UA OTHER_CHROME、window.chrome=false。这证明复用未到发布页，尚不能归因于凭证失效或 UA。下一步限定同一复用 context 在官方 HOME 且无登录/DOM 异常时只读再次导航固定官方 CREATE，观察结果；不把 HOME 当成功、不取消复用门禁。
- HOME reentry 诊断 wrapper SHA256 `171aaf194d0f2ef0338b3a0a9351645e0d18a656ca46e1a1c97c14bf813f77c7`：receipt `auth_diagnostic_receipt_1790573118.json`，同一 reuse context 第二次固定 CREATE 导航 5.36 秒后仍官方 HOME、无登录提示、guard=false/PAGE_UNREADY。排除简单首次初始化需再导航的假设；原授权仍 FAILED，无生产指纹变更。
- 下一候选修复范围：统一现有 uploader 初始/内部复用、keepalive、独立 verifier 的既有 UA 与 init_script 配置，保持真正新 context 和所有严格发布门禁。浏览器配置差异已确认，但其是否导致平台 HOME 跳转仍须实际验收，不预先宣称根因已修复。

## 2026-09-28 14:15 收敛验收：共享上下文候选代码 PASS

- Antigravity 提交 `fe217bfc0d27ae33a6f4a6cdf12d796d9bf737d9`。Codex 核查4个业务文件及浏览器测试，沿用原 uploader 配置、移除重复代码，未放宽发布页/独立上下文门禁，relogin 不加载旧 state。
- 必要测试 `/private/tmp/video-pytest-av23qq_m`：20 passed；隔离边界及 pytest exit 0；源码 manifest `db2601254c289d2c1a4ee73af802f218e3c2f618a47fb56150b9a91473a60fcd`。Codex 独立核对5个变更文件与成功测试快照逐字一致，不重复同一套测试。
- 放行一次最终真实候选验收：`/private/tmp/verify_wechat_auth_final_candidate.py` SHA256 `7ea1522a3334a6ab5da207b9b610b26d6db0d16d52346da63d41f1a539aca16a`。仅把此前已审 parent 的 uploader 入口改为原业务脚本，去除诊断 wrapper 和 HOME 再导航；仍持生产锁、空白自定义状态、禁 Telegram、120秒有界与生产文件指纹保护。
- 不再重复既有成功阶段或扩展边缘测试。后台系统权限尚未获新确认，生产采用仍须实际复用成功；本节不是生产 PASS。

- 最终候选验收启动后 desktop_preflight=READY，但在真实生产锁处退出 LOCK_BUSY，未触发新的微信授权。只读核查生产 login-only PID 8346（PPID 95170）运行约12分钟；14:05:16 日志明确 ACCESSIBILITY_DENIED。保留该进程，本次未发信号或改生产凭证。
- 已向用户明确请求开启生产 Python 3.12 辅助功能权限。此项是无人值守启动链的具体阻断；答复前不改系统设置、不反复前台授权。当前代码候选已提交且必要测试通过，生产尚未采用。

- 用户已明确同意开启生产 Python 3.12 辅助功能权限。Codex 通过系统设置点击现有 python3.12 关闭开关后，macOS 要求管理员密码认证；尚未确认开关开启。已请求用户在本机系统弹窗自行认证，不接收聊天密码。继续后台验收前须回读开关为 on。

## 2026-09-29 后台验收记录（无人值守 PASS 已撤回，见末节）

- 用户确认完成管理员认证后，Codex 回读 python3.12 辅助功能为 on。微信桌面未运行，已通过正常界面恢复进入微信；未操作聊天内容。
- 后台一次性验收 `background_receipt_1790655756.json` 显示 READY、快捷按钮已点击，但 screencapture 连续退出 1。相同 Python 通过 launchd 调用只读 `CGPreflightScreenCaptureAccess` 返回 false。原 NO_SCOPED_AUTH_WINDOW 掩盖了录屏权限缺失，不能继续据此重试授权。
- 用户在本轮明确授权开启 Python 屏幕录制。Codex 在系统设置开启现有 python3.12 开关，回读 on；同一后台检测从 false 变为 true。未写 TCC 数据库，未扩大程序已有的候选小窗口截图范围。
- 最终原程序候选 `fe217bfc0d27ae33a6f4a6cdf12d796d9bf737d9` 回执：`/Users/ryusei/.codex/worktrees/wechat-auth-remediation/Video-precessing/output/acceptance_artifacts/background_receipt_1790656034.json`。结果 exit=0、CLICKED_VISUAL、quick_authorization_succeeded=true、authorized_this_run=true、auth_success=true；独立新浏览器 origin_verified=true、positive_controls_verified=true、login_required=false、success=true。生产文件指纹一致。2026-09-29 12:27:59 BJ 完成独立复用。
- **原 Codex 上线审查 PASS（绑定 fe217bfc）已因用户报告手动点击而撤回。** 保存与独立复用结果保留，自动点击效果尚未验证；禁止依据本次回执集成上线。
- 临时后台验收使用 RunAtLoad=true、KeepAlive=false，完成后已 bootout。较早 launchctl submit 失败任务曾被 launchd 自动重启，发现后已移除任务并只终止本次孤立候选进程组，未信号生产服务。此后禁止用失败会重启的 submit 方式运行一次性登录验收。
- 首评当前账本：publication 1255 / q1H-Mxo4CXs，SUBMITTED_BOUND，interaction UNCERTAIN，attempt_count=2。用成功候选会话和生产锁仅做 verify_only=true 回读，结果 COMMENTED、无错误；证据目录 `output/acceptance_artifacts/comment_readonly_20260929/attempt-20260929T043011.612691Z-d650f7b750ba49aead74b4c8464c81e3/`。未发新评论、未更新账本。近期另有 6 个可评论条目未入互动账本，不能宣称全部互动积压清零。
- 12:30 BJ 生产 `/api/stats` active=1 / TRANSCRIBING=1，实际 auto-caption PID20201、ffmpeg PID32525 仍在渲染；生产发布优先租约为空。**尚未合并、push、替换生产会话或重启。** 必须等现有加工空闲后集成，再以标准生产登录流程生成会话，核查调度和已有 UNCERTAIN 评论只读核对。
- Antigravity 已完成不改工作区的合并预检：main `3d53e80` 与候选 `fe217bfc` clean merge，预检树 `357ed4f5534ac6ec187fa646ea593f63b876e8b4`。执行清单位于候选 `docs/handoffs/2026-09-27-wechat-login-antigravity/DEPLOYMENT_READY_20260929.md`，CLI 会话 56646 待命；后续须重新核实当前主干和全部活动进程，不能只依据旧 PID 退出判空闲。
- 12:34 BJ 控制台仍 active=1。临时每30分钟空闲上线跟进创建被宿主自动审批拒绝（一次性上线授权不足以授权含合并/推送/重启的持久自动化），**自动化未建立**。已明确告知用户并单独请求限本次、完成即停用的定时收尾授权；答复前不以 shell 循环等其他方式绕过此拒绝。

## 2026-09-29 用户纠正：人工点击，无人值守验收撤回

- 用户明确报告：最近一次微信授权方框停留很久，用户为避免挡住工作手动点击了确定。`background_receipt_1790656034.json` 因此属于人工协助授权；保留原回执，不伪造或覆盖历史证据。
- CLICKED_VISUAL 只能证明程序派发鼠标事件，不能证明按钮响应。本次页面就绪、保存及独立新上下文复用成功仍有效，但不能支持无人值守成功。
- 当前结论 REQUEST_CHANGES，撤回绑定 fe217bfc 的生产 PASS。尚未集成、推送或重启，Antigravity 已收到暂停上线及聚焦 native click 实效的整改要求。此前临时定时上线问题已失去前提，不建立该自动化。
- 下一轮只核查实际点击交付及结果，保留可信窗口、OCR、坐标范围和时限约束；禁止仅凭事件派发宣告自动点击成功。真实试验由 Codex 串行安排，任何人工点击都使该轮无人值守验收无效。

### 自动点击整改候选：代码审查通过，待无人代点实测

- Antigravity 最小改动限于 `wechat_auth_vision.js`、`wechat_desktop_auth.py` 及其单元测试：增加 move/down/60ms hold/up、clickState=1，延时后重新核验前台和精确窗口几何，释放放在 finally；仅明确读取原 PID+窗口 ID 不再可见才记录 VISUAL_WINDOW_DISMISSED。
- 派发尝试上限为 2，尚未找到可信授权窗口不消耗预算；点击未确认保留 VISUAL_CLICK_UNCONFIRMED。最终业务授权成功仍取决于正向网页控件和独立新上下文复用。
- Codex 独立核验 `/private/tmp/video-pytest-himrfgfi/receipt.json`、pytest.log 及源码快照：22 passed，隔离探针和测试 exit 0，三个文件与通过快照逐字一致。manifest `24c718599fdae01cf086915d386f0f1671060f37264406ba0683d3fee20fe5d3`。
- 仅放行冻结候选后的一次后台真实验收；生产 PASS 尚未恢复。测试通过不证明用户未介入，也不证明底层事件已被微信接收。

## 2026-09-29 14:11 后台点击修复实测 PASS（候选 f1e74cc）

- 候选 `f1e74cc465f1d28be3b91b72016e1e3c587aaf60`，仅 3 个点击修复/测试文件；保留人工辅助旧回执及撤回记录。
- 真实回执 `candidate/output/acceptance_artifacts/background_receipt_1790662252.json`：后台 preflight READY，native_click_started=27.428s、native_click_dispatched=true=27.632s，原窗口 visible=true=27.869s、visible=false=28.168s，quick_login_ready=true=35.574s。仅发生一次原生点击派发。
- 桌面结果 VISUAL_WINDOW_DISMISSED，原 uploader 授权保存成功；14:11:35 BJ 独立新浏览器 origin_verified=true、positive_controls_verified=true、login_required=false、success=true。生产文件指纹一致。Codex 本轮没有通过 CUA 代点，只读检查授权框已不存在；未收到用户本轮介入报告。窗口响应、业务授权和独立复用均有证据。
- 验收 wrapper 仅记录白名单阶段及耗时，快捷授权失败即结束本轮、不等待人工扫码；未修改成功业务路径。parent SHA256 `15ba33c7f58b33b5ffcfc87d98ddbcf35306426c21728eb235ee40c082b8f43a`，observer SHA256 `c93a2f4c7dec1b82bc8d106b832081869e03ca5c43e56f1379340485b67e0510`。
- 一次性 LaunchAgent KeepAlive=false，执行后已 bootout。未发布视频、未发评论、未替换生产会话。
- **Codex 放行该候选在生产空闲时集成上线。** 14:12:12 BJ 仍 active=1，auto-caption PID55489 和 FFmpeg PID57831 正在加工另一条视频。因此生产 main 仍为 3d53e80，尚未合并、推送或重启；不得把候选 PASS 报成生产已采用。无需重复该成功授权测试。

## 2026-09-29 16:17 用户要求的可视化完整复验

- 用户明确要求再次运行完整登录流程，并在电脑旁观察。候选仍为 `f1e74cc465f1d28be3b91b72016e1e3c587aaf60`；本次显示浏览器，原程序执行授权，Codex 未通过界面工具代点。运行时仅使用固定程序和本机离线 OCR，不调用大模型。
- 回执：候选 `output/acceptance_artifacts/background_receipt_1790669808.json`。仅一次原生点击派发（31.345s），原授权窗口于 31.901s 不再可见，相差 0.556s；38.129s 网页登录就绪。授权、保存均成功，16:17:36 BJ 独立新浏览器复用通过，生产文件指纹未变。
- 当前人工作用记录为 `not_observed`，已向用户索取现场观察反馈；如用户报告手动点击，应撤回本轮无人值守结论，保留原始回执。程序证据本身不替代用户证言。
- 临时一次性 LaunchAgent 已 bootout。16:20:09 BJ 控制台只读回读仍 active=1 / TRANSCRIBING=1；生产 main 尚未采用候选，未合并、推送或重启。不再额外重复授权。
- 用户随后明确现场确认：“很好，我看着没问题的”。结合本轮程序点击、窗口关闭、网页就绪及独立复用证据，本轮完整自动登录验收通过；不再重复登录测试。16:20:48 BJ 再查生产仍 active=1 / TRANSCRIBING=1，继续保留空闲后上线条件。

## 2026-09-29 16:51 上线执行请求与空闲门禁

- 用户明确要求“合入上线”。main 仍为 `3d53e8084383001ac57360e3bb2b171ab8d4e5f9`；保护原有未提交验收文档及未跟踪 topic_clues 文件。
- 16:52:11 原渲染退出，active=0，但巡航随后仍有抖音只读核查；未在该时刻合入。16:54:41 仪表盘自动调度已启动新的加工 PID10357 及独立发布，active=2。一次性部署互斥保护在 pipeline_job.lock 检出 BUSY 后立即退出，未留下持锁进程。
- 16:56:24 发布进程已退出，当前仅 TRANSCRIBING=1；新增 LOGIN_REQUIRED=2 为原生产流程的状态，尚未采用修复版本。不得把此状态当作候选实测失败。
- Antigravity 交互 CLI 完成合并预检：`merge-tree --write-tree 3d53e80 f1e74cc` exit=0，无冲突，合并树 `59b02ab4a3b88ac0431728dabc446b4dce353158`。未实施 merge/push/restart。非交互 CLI 曾因无法显示命令权限提示拒绝预检，已改为交互逐项批准，不修改持久权限或绕过权限。
- 已向用户说明 AGENTS.md 空闲约束，并请求是否允许停止当前可续跑加工、保留检查点后上线；答复前不终止加工。无后台自动上线任务，Antigravity 此轮只读预检后待命。

## 2026-09-29 21:28 已合入、推送及生产采用：PASS

- 用户再次明确要求“合入上线”。21:24:43 BJ 生产已自然空闲（active=0，无加工、发布或登录子进程），无需终止加工。Codex 取得巡航、作业、加工、微信发布优先和浏览器会话的临时互斥锁，完成部署后已释放；未改变持久调度配置。
- Antigravity 执行合并及推送，合并提交 `e152954b6f0f54784f1727e92e3ead0e90e7705b`；Codex 独立确认 tree=`59b02ab4a3b88ac0431728dabc446b4dce353158` 与预检一致，远程 `refs/heads/main` 回读为同一提交。原未跟踪 topic_clues 代码和测试保持原状。
- Codex 按标准入口重启控制台及 Bot：控制台 PID92708，21:26:35 BJ 启动并绑定 9100；Bot PID92980，21:27:04 BJ 启动。控制台日志确认自动登录保活看门狗已启动，新接口已返回结构化状态字段。
- 合入后的独立生产会话复用回执 `output/acceptance_artifacts/wechat_production_reuse_20260929.json`：官方来源、正向发布控件均通过，login_required=false、success=true。未重新登录、未弹出授权框、未上传视频或发表评论。
- 原生产会话迁移后先显示“未经验证”，这是缺少新格式验证记录。执行一次原业务 `wechat_keepalive.py --dwell 15`，21:28:07 BJ 正向控件验证、原子保存与结构化记录均成功（exit=0）。没有手写成功标记，没有复制候选凭据，没有伪造授权时间。
- 最终线上 `/api/wechat/status`：logged_in=true、status_label=“✅ 授权且已验证”、is_running=false、qr_exists=false。自动重登、保活、桌面快捷授权、视觉识别回退四项生产配置均为 true，下一次保活计划已记录。
- 本轮微信登录修复上线完成。首评既有不确定账本与其他平台待核查任务不属于本轮登录上线完成结论，不据此宣称全部发布或互动积压已清零。
- 协作收敛经验：Codex 先持有部署互斥窗口再给 Antigravity 一次明确的合入/推送指令；逐项许可、不修改持久权限；以提交树、远端回读、新服务进程和业务状态闭环验收。候选授权已有人证时，生产已有会话通过正常保活完成验证迁移，不重复授权测试。
