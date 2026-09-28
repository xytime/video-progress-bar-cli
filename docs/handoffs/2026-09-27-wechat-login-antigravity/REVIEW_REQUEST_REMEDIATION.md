# Review Request — 微信视频号助手自动登录与状态凭证整改交付 (WX-AUTH-20260927)

## 基本信息
- **工单**: WX-AUTH-20260927
- **执行方**: Antigravity
- **独立审查方**: Codex
- **目标主干**: `main`
- **上一轮审查结论**: `REQUEST_CHANGES` (基于候选 `548a243`)
- **本次修复后冻结候选 Commit**: `617411c38109ed3dc40d5f2d6cd3bcc62881e8af` (`fix(wechat): remediate auth state evidence, strict page contract, failure categories and web status binding`)
- **基线 Commit (Fork Point)**: `aa58c80521e4277ec81d11ff928ee5d1df6395ec`
- **上一轮候选 Commit**: `548a243beaadb0203519b559bdee63cd5120dae3`
- **当前状态**: 已完成整改与隔离测试，冻结候选提交，等待 Codex 独立复审及下一步 PASS。

---

## 1. 交付物与校验指纹

### 补丁文件与 SHA256
| 补丁文件 | 范围 | SHA256 |
|---|---|---|
| `docs/handoffs/2026-09-27-wechat-login-antigravity/evidence/candidate-remediation-v2-full.patch` | `aa58c80..617411c` (全量) | `454fada724e5d34eb46e51d0a1ba3c7090750b642517388a9510a226e052a955` |
| `docs/handoffs/2026-09-27-wechat-login-antigravity/evidence/candidate-remediation-v2-incremental.patch` | `548a243..617411c` (增量) | `fe0a5237ec963f257fbb847403f7ff6f923afc2aac7445e85d83ec643cdf529a` |

### 修改源码与测试文件 SHA256 清单 (15 Files)
```text
0bfed184cbf8e38d49bf4ce34a0d7af605174d55033ee5532ceefab6adf79ac6  scripts/verify_wechat_session_reuse.py
9c4f5583e83ed762feb676063a2b8bf752343fc97f9533cfb09327ebf26b882f  scripts/wechat_keepalive.py
f866a2235032aa005e5077fe84ccffd2d8030f2c77fb832ca79cb0e2380adb0d  scripts/wechat_uploader.py
179225b4056b86a4fe9d79e525495c5eda9a18006e37982616b48d85c7f5916f  src/bot/formatter.py
7c0e0de114880c23a89150297d8b43ba08be15e58d9d28352af0b93c9d0a36dc  src/bot/telegram_bot.py
de3ddfe4ec2c7372c83182b5e88e237348488c6c21115f233b42775fceae51ab  src/video_processing/core/wechat_auth_state.py
4a7070caf04fa1bdc883e4a8882126ef7c2fee2a518218861188798fcf74e59c  src/video_processing/core/wechat_page_contract.py
133ed67f3a963c68b7366eeb5a4271d69078b875b7c6a22213034901a639a36e  src/web/app.py
171221fb1860b872f5ce0a6d07ecd036fa6dc0db06ffe1f0aa77dc840b6b33e0  tests/browser/test_wechat_keepalive_browser.py
ed106758fd24411fcbc71448971d2fc400732e91b4dd2df2eded5c282ca9becf  tests/browser/test_wechat_quick_login.py
b302f265fc94005ba8896cec343518025dfd80f8855f9f23d0700f2ffdac545d  tests/unit/test_bot_formatter.py
f446b303a22839eca53b968c62600e99b8a1f43d27fe4c9c6cb93f9e8d83859f  tests/unit/test_wechat_auth_state.py
31b7fa7a3ab102c19cef05f88d139fcca81a6a2634a3a1ffdacf03739f13a116  tests/unit/test_wechat_auto_relogin.py
a65c305deb081c9ae82051524894c60aef435ac9498cae6112bb02e8c2f8247b  tests/unit/test_wechat_keepalive.py
4c6442edb29c56d9bbd6f5aaa84e9f59395beef6ac6e3c5e4c3f39ba5e042457  tests/unit/test_wechat_keepalive_warn.py
27de1b24fa76bf77dc9ad8d7b494b14101092cbeac18e469dc835e04149645f1  tests/unit/test_wechat_login_recovery.py
```

---

## 2. 隔离测试执行与证据回执

根据项目铁律与测试隔离宪法，所有测试均使用 `scripts/run_isolated_tests.py` 在独立沙箱快照根下运行，严禁直接运行未经沙箱隔离的裸 pytest。

### 回执 1：隔离单元测试 (90 passed, 20 subtests passed)
- **证据目录**: `/private/tmp/video-pytest-5iah81wu`
- **执行命令**: `.venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_wechat_auth_state.py tests/unit/test_wechat_keepalive.py tests/unit/test_wechat_keepalive_warn.py tests/unit/test_bot_formatter.py tests/unit/test_telegram_bot.py tests/unit/test_wechat_desktop_auth.py tests/unit/test_wechat_auto_relogin.py tests/unit/test_wechat_login_recovery.py`
- **测试结果**:
  - `90 passed, 20 subtests passed, 2 warnings in 16.72s`
  - 进程退出码: `0`
  - 源码指纹: `10957408e6c783456aca8d7ed98bc57d2b18c740056ab7f2da7dfd801ae0ddc0`
  - 沙箱 profile 指纹: `3910ea7e4bdfa64d2e6f44a3be8e0b638fb21e450080ca288b579e1d48e98fe1`
  - 日志绝对路径: `file:///private/tmp/video-pytest-5iah81wu/pytest.log`

### 回执 2：真实隔离 Chromium 浏览器测试 (17 passed)
- **证据目录**: `/private/tmp/video-pytest-l_oftaux`
- **执行命令**: `.venv/bin/python scripts/run_isolated_tests.py --browser -- -q tests/browser/test_wechat_keepalive_browser.py tests/browser/test_wechat_quick_login.py`
- **测试结果**:
  - `17 passed in 68.09s (0:01:08)`
  - 进程退出码: `0`
  - 源码指纹: `10957408e6c783456aca8d7ed98bc57d2b18c740056ab7f2da7dfd801ae0ddc0`
  - 真实 Chromium 版本: `148.0.7778.96` (`chromium_headless_shell-1223`)
  - 浏览器运行时指纹: `9543a7723dbacd714343a92fe586afb74dce38a83b760c414888e90737934fb9`
  - 日志绝对路径: `file:///private/tmp/video-pytest-l_oftaux/pytest.log`

---

## 3. 整改项落实与架构设计核查

针对 Codex 在 `docs/handoffs/2026-09-27-wechat-login-antigravity/REVIEW_RESULT_REMEDIATION.md` 中签发的全部必须修正项及后续追问，已完成如下重构与收口：

### 3.1 消除乐观判断与单源页面契约 (`src/video_processing/core/wechat_page_contract.py`)
- **单一真相源**: 创建独立核心模块 `wechat_page_contract.py`，提供 `is_official_wechat_origin`、`is_official_create_url`、`has_publish_positive_controls`、`wait_for_publish_ready_with_spa_guard` 等判据，供 `uploader`、`keepalive` 与 `verify_wechat_session_reuse` 统一调用，消除三者契约漂移。
- **严格域名与源白名单**: 必须为 `https://channels.weixin.qq.com` 且端口必须为默认 443，拒绝非默认端口与 URL userinfo。
- **强特征发布控件**: 彻底移除了空泛的通用上传按钮匹配（如 `.upload-btn:has-text('上传')`），严格限定为接受 `video/*`、`mp4` 的 file input，或包含“上传视频”文案的强特征按钮。
- **Fail-Closed 异常防护**: `wait_for_publish_ready_with_spa_guard` 中当轮发生任何 DOM 异常立即记录并重试，绝不跳过报就绪。

### 3.2 凭据元数据与结构化状态引擎 (`src/video_processing/core/wechat_auth_state.py`)
- **唯一派生与绝对路径绑定**: 元数据文件基于真实 `state_file` 绝对路径规范派生（`f".{state_path.name}.meta.json"` 并绑定完整 `canonical_state_path`），彻底解决 `wechat.json` 与 `wechat_state.json` 冲突。
- **生产目标严格隔离**: `is_wechat_state_target()` 严格比对 canonical 绝对路径与 `settings.project_root / "output" / "wechat_state.json"`，同名不同目录测试绝不继承/覆盖生产 marker 或 flags。
- **白名单字段与固定分类码**: 
  - 写入与读取统一持久化固定大写分类码（`PAGE_UNREADY`, `STORAGE_FAILED`, `INVALID_ORIGIN`, `REUSE_VERIFICATION_FAILED`, `NETWORK_TIMEOUT` 等）；
  - 彻底去除动态 URL 与异常堆栈自由文本存储；展示层动态映射中文摘要，并在 Telegram `/last_login` 输出 `last_auth_attempt_display`。
- **时序与事实判定**:
  - 授权时间与最近验证时间基于事件时间戳独立比较，真实更新授权成功不会被旧的 `last_keepalive_status` 误判失效；
  - 拒绝单凭历史 marker 报绿：缺失正向验证、来源异常或未知失败绝不绿；
  - 未来时间戳防御：超过容忍窗口自动降级为 UNKNOWN，绝不截断为 0 误报绿色；
  - 持久化实际计划检查时刻 `next_keepalive_scheduled_at`。

### 3.3 登录与独立复用流程原子化 (`scripts/wechat_uploader.py`)
- **阻断错误来源**: `_try_wechat_quick_login` 遇到 `INVALID_ORIGIN` 或 `DOM_ERROR` 立即退出，不遍历 iframe 点允许；支持自定义 `state_file` 传参，记录尝试失败绝不触碰生产目标。
- **有界独立复用校验**: `_wait_and_save_login` 当 `context.browser is None` 时严格拒绝；保存至隐藏临时文件后，通过全新独立 `BrowserContext` 导航至官方发布页，通过 `wait_for_publish_ready_with_spa_guard` 校验正向视频发布控件；校验通过后原子重命名替换目标文件。
- **失败保留旧凭证**: 若存储或复用失败，记录结构化固定分类码，清理临时文件，保留旧 state，并重新抛出异常。
- **通知脱敏**: 登录通知仅陈述“已通过独立复用验证”，不夸大声称恢复任务。

### 3.4 Web 状态接口与自动化流程绑定 (`src/web/app.py`)
- **`/api/wechat/status` 改造**: `_wechat_login_marker_active` 深度复用 `evaluate_wechat_session_status`，仅当结构化状态处于验证有效事实时才返回 True，历史 marker 无法在保活失败后伪装有效。
- **`_start_wechat_login_flow` 绑定**: 绑定子进程退出码与本次 `post_auth_at > pre_auth_at` 及 `post_auth_at >= start_ts - 2.0` 时间戳，未完成有效授权的子进程退出绝不恢复任务。

### 3.5 历史归因完整性
- 恢复了 `src/bot/telegram_bot.py` 中被误删的 `1.26.0 Codex /last` 历史归因行；
- 保留 `scripts/wechat_keepalive.py` 原有时序表格并规范追加本次修改版本记录。

---

## 4. 明确未实测项 (Limitations & Non-Goals)

1. **真实外网与微信视频号生产发布**:
   - 严格遵守宪法与隔离铁律，未连接腾讯官方真实外网接口，未在生产账号上进行真实视频发布；所有真实 Chromium 测试均在隔离沙箱与本地路由接管下完成。
2. **移动端扫码真实交互**:
   - 扫码登录的人工手机端交互属于物理动作，由真实隔离 Chromium 路由模拟和桌面快捷登录原生适配器逻辑覆盖，未进行真机扫码。
3. **生产目录与凭据隔离**:
   - 未改动生产目录 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing`；
   - 未读取或写入真实生产 `.env` 凭证。

---

## 5. 回退方案 (Rollback Plan)

若 Codex 独立复审需要回退或放弃本轮整改：
1. **工作区分支重置**:
   ```bash
   git reset --hard aa58c80521e4277ec81d11ff928ee5d1df6395ec
   ```
2. **或应用逆向补丁**:
   ```bash
   patch -p1 -R < docs/handoffs/2026-09-27-wechat-login-antigravity/evidence/candidate-remediation-v2-full.patch
   ```
3. **生产环境无副作用**:
   - 本次整改完全在隔离工作树 `candidate/wechat-auth-remediation` 中进行，未合并至 `main`，未推送到 `origin`，生产环境完全零污染。

---
**交付结论**: 候选 Commit `617411c38109ed3dc40d5f2d6cd3bcc62881e8af` 现已完全冻结，所有证据均已存档，请 Codex 进行独立审查并签发结论。
