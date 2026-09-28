# Review Request — 微信视频号助手自动登录与状态凭证整改交付 (WX-AUTH-20260927)

## 基本信息
- **工单**: WX-AUTH-20260927
- **执行方**: Antigravity
- **独立审查方**: Codex
- **目标主干**: `main`
- **基线 Commit (Baseline Full SHA)**: `aa58c8068951d6ec941d63334b55a7b042ae4ae0` (通过 `git rev-parse aa58c80` 实取)
- **上一轮候选 Commit**: `548a243beaadb0203519b559bdee63cd5120dae3`
- **本次最终冻结候选 Commit (Candidate Full SHA)**: `3054114c91c636fd5833c693c13bd82f015016d3` (`fix(wechat): complete remediation for late authorization timing, trusted frame origin and management page dom error guard`)
- **当前状态**: 已完成全部缺陷修复与隔离测试，已冻结提交，等待 Codex 独立复审及下一步 PASS。

---

## 1. 补丁与指纹清单

### 补丁文件与 SHA256
| 补丁文件 | 范围 | SHA256 |
|---|---|---|
| `docs/handoffs/2026-09-27-wechat-login-antigravity/evidence/candidate-remediation-v3-full.patch` | `aa58c80..3054114` (全量) | `6580da0d5f453c2f60d04bdd1424a4671745db1952a8ae8ed2a6a650cbd565c0` |
| `docs/handoffs/2026-09-27-wechat-login-antigravity/evidence/candidate-remediation-v3-incremental.patch` | `548a243..3054114` (增量) | `2fbc0619dd4f4425862adff598a0ab9780ba64b03b3f8b341a2f74645ec542ad` |

### 修改源码与测试文件 SHA256 清单 (17 Files)
```text
0bfed184cbf8e38d49bf4ce34a0d7af605174d55033ee5532ceefab6adf79ac6  scripts/verify_wechat_session_reuse.py
9c4f5583e83ed762feb676063a2b8bf752343fc97f9533cfb09327ebf26b882f  scripts/wechat_keepalive.py
e7df35bdf9bf0bb67d8f583995f5cc1b069d2551525a7a7d4be10e3012929e06  scripts/wechat_uploader.py
179225b4056b86a4fe9d79e525495c5eda9a18006e37982616b48d85c7f5916f  src/bot/formatter.py
a71ca9d3625482ce0752538cb3ffaf258f844a49646b9ec7be533dd531238495  src/bot/telegram_bot.py
4ffb717bfe4c1d4e2a149ef784d1bc9170284fb8e9ee26359f4705574341909a  src/video_processing/core/wechat_auth_state.py
2f026a7e0c40698066e2c43144bf56449177e770fc569263435c24e03099feae  src/video_processing/core/wechat_page_contract.py
133ed67f3a963c68b7366eeb5a4271d69078b875b7c6a22213034901a639a36e  src/web/app.py
171221fb1860b872f5ce0a6d07ecd036fa6dc0db06ffe1f0aa77dc840b6b33e0  tests/browser/test_wechat_keepalive_browser.py
a4ff4985223321db80f2d721111663b6a98dfb02cc607b220c326071ef2e86be  tests/browser/test_wechat_quick_login.py
b302f265fc94005ba8896cec343518025dfd80f8855f9f23d0700f2ffdac545d  tests/unit/test_bot_formatter.py
1b7fc77b7dbd809071066c0e5a6067b56a5eec5a805988e4b85daeecf60cff13  tests/unit/test_wechat_auth_state.py
31b7fa7a3ab102c19cef05f88d139fcca81a6a2634a3a1ffdacf03739f13a116  tests/unit/test_wechat_auto_relogin.py
a65c305deb081c9ae82051524894c60aef435ac9498cae6112bb02e8c2f8247b  tests/unit/test_wechat_keepalive.py
4c6442edb29c56d9bbd6f5aaa84e9f59395beef6ac6e3c5e4c3f39ba5e042457  tests/unit/test_wechat_keepalive_warn.py
27de1b24fa76bf77dc9ad8d7b494b14101092cbeac18e469dc835e04149645f1  tests/unit/test_wechat_login_recovery.py
09fae4860011ec7f5be2465eb19eaef5e1564f51e069151e2bc0164c8c7d6928  tests/unit/test_wechat_quick_login_authorization.py
e7e1d528b8b0e8c8dcbe0c3ea172fa829875bbbb06aeb4803d52368c85faad06  tests/unit/test_wechat_uploader_notify.py
```

---

## 2. 隔离测试执行与证据回执

### 回执 1：单元测试全量套件 (105 passed, 20 subtests passed)
- **证据目录**: `/private/tmp/video-pytest-kmv6z3m9`
- **执行命令**:
  ```bash
  .venv/bin/python scripts/run_isolated_tests.py -- -q \
    tests/unit/test_wechat_auth_state.py \
    tests/unit/test_wechat_keepalive.py \
    tests/unit/test_wechat_keepalive_warn.py \
    tests/unit/test_bot_formatter.py \
    tests/unit/test_telegram_bot.py \
    tests/unit/test_wechat_desktop_auth.py \
    tests/unit/test_wechat_auto_relogin.py \
    tests/unit/test_wechat_login_recovery.py \
    tests/unit/test_wechat_quick_login_authorization.py \
    tests/unit/test_wechat_uploader_notify.py
  ```
- **测试结果**:
  - `105 passed, 2 warnings, 20 subtests passed in 20.39s` (Exit code: `0`)
  - `source_manifest_sha256`: `bd00d31aae042c97034579e20a3bee827afd55e3650beb38ea17b17418925b37`
  - `profile_sha256`: `70fcbb69a0a5d46ac8f2f15e83aeeaf30fdddc4eb8304d509ab6ead57eeefcce`
  - 日志绝对路径: [pytest.log](file:///private/tmp/video-pytest-kmv6z3m9/pytest.log)

### 回执 2：真实隔离 Chromium 浏览器测试 (19 passed)
- **证据目录 1 (前 18 项全部通过)**: `/private/tmp/video-pytest-0fvnvevu`
- **证据目录 2 (管理页 DOM 探针异常抛错阻断复验通过)**: `/private/tmp/video-pytest-xfhtooiv`
- **执行命令**:
  ```bash
  .venv/bin/python scripts/run_isolated_tests.py --browser -- -q \
    tests/browser/test_wechat_quick_login.py -k test_uploader_management_page_fails_hard_on_dom_error
  ```
- **测试结果**:
  - `1 passed in 17.33s` (Exit code: `0`)
  - `source_manifest_sha256`: `75cedaf85b348e80f33a9a214f149c0658c0c28fc24184f5cd0d31a07e58b08f`
  - `profile_sha256`: `7af64506bcc6c3c99c6c046200e71819e9e2dd2abafbc54d1e828f734971a4ab`
  - 真实 Chromium 版本: `148.0.7778.96` (`chromium_headless_shell-1223`)
  - 浏览器运行时 SHA256: `defa30c09acc8bf339a165d14d666c20b830e4f1bf91b9bd00612ec98897bdd4`
  - 日志绝对路径: [pytest.log](file:///private/tmp/video-pytest-xfhtooiv/pytest.log)

---

## 3. 本轮最终整改与架构收口清单

1. **bot `auto_relogin_started` 15min 有效期与文案修正**:
   - `src/bot/telegram_bot.py`: 检查 flag 存在且未超过 15 分钟（`time.time() - flag.stat().st_mtime < 15 * 60`），过期 flag 不再作为活跃标记；
   - `src/video_processing/core/wechat_auth_state.py`: 文案改为 `“自动重登近期已触发，结果以最近授权记录为准”`，不将 flag 误称为活跃进程。
2. **`_trusted_wechat_login_frame` 严格拒绝 non-default port 与 userinfo**:
   - 在 `src/video_processing/core/wechat_page_contract.py` 中新增 `is_official_wechat_frame_origin`；
   - 必须为 HTTPS、默认 443 端口、无 userInfo，且 host 为 `channels.weixin.qq.com` 或 `open.weixin.qq.com`；
   - 在 `tests/browser/test_wechat_quick_login.py` 中补充 `test_try_wechat_quick_login_zero_clicks_on_untrusted_frame_origin`，断言伪造 frame 下按钮点击计数严格为 0。
3. **`run_uploader` 管理页与发布页分支中遇到 DOM_ERROR 拒绝 fail-open**:
   - 在管理页与创建页分支中，`check_explicit_login_prompt` 返回 `dom_err=True` 时立即抛出 `RuntimeError`，绝不因处于 list URL 而误判认证通过；
   - 在真实 Chromium 浏览器测试中验证抛错与零后续操作（Mock 数量仅 2 个，严格符合 Mock gate）。
4. **迟到授权 (29s) 时序回归彻底修复**:
   - `scripts/wechat_uploader.py`: 在点击“允许”按钮后，**立即**以剩余期限为上限执行正向发布页判定（`wait_for_publish_ready_with_spa_guard`），成功直接 `return True`；
   - 获准后设置 `approved_this_cycle = True` 并执行 `continue`，**彻底跳过本轮末尾的 `page.wait_for_timeout`**，避免边界耗尽超时；并在循环外部增加有界末次检查（<=1.0s），原样保证整个 30s deadline 授权检查与 `now < 30` 断言。
5. **元数据命名订正**:
   - 规范确认为 `{state_file.name}.auth_state.json`（由 `get_auth_state_file_path(state_file)` 唯一派生），与源码实际逻辑完全一致。

---

## 4. 严密真实验收脚本设计 (已就绪，未执行)

已在 `/private/tmp/verify_wechat_auth_live_candidate.py` 生成专用真实验收脚本。**该脚本处于受保护状态，未经明确 PASS 严禁执行。**

### 核心安全与隔离机制：
1. **真实生产排他锁**: 父进程获取生产目录 `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/wechat_state.json` 的 `WeChatSessionLock`，防止生产流水线并发冲突；
2. **显式环境变量与安全脱敏**:
   - `ENABLE_WECHAT_DESKTOP_QUICK_LOGIN=true`
   - `ENABLE_WECHAT_DESKTOP_VISUAL_AUTH_FALLBACK=true`
   - `WECHAT_DESKTOP_QUICK_LOGIN_TIMEOUT_SECONDS=30`
   - 彻底清除所有 `TELEGRAM_*` 环境变量，杜绝向外发送临时二维码或通知；
3. **有界受控执行**:
   - 子进程限定 `python scripts/wechat_uploader.py --login-only --relogin --state <custom_state>`，硬超时上限 120s；
4. **严格判定与非零退出**:
   - 必须满足 `res.returncode == 0`；
   - custom 元数据 `authorized_at >= start_ts - 2.0`；
   - `last_auth_attempt_status == "SUCCESS"`；
   - 任一不满足则非零退出；
5. **独立复用与双向 Receipt**:
   - 调用已审 `verify_session_reuse(custom_state)` 输出白名单 receipt；
   - 对生产旧 state 进行只读 `verify_session_reuse(prod_state)` 并输出 receipt；
   - 生产 marker、flags、state 的 stat 与 sha256 前后比对，绝不读取凭据载荷内容；
   - 临时凭证安全归档于 `SOURCE_ROOT/output/acceptance_artifacts`（受 `.gitignore` 保护），不自动删除唯一凭据。

---

## 5. 回退方案 (Rollback Plan)

- **生产无污染**: 本次整改完全在隔离 worktree `candidate/wechat-auth-remediation` 中进行，未合并至 `main`，未推送到 `origin`，生产物理目录零变动。
- **上线回退程序**:
  若上线后需要回滚，**严禁执行 `git reset --hard`**（防止丢弃主干无关提交与未提交工作），必须遵循规范：
  ```bash
  # 在主干空闲时创建 revert 提交并推送
  git revert -m 1 <merge_commit_sha> -n
  git commit -m "revert: rollback WeChat auth remediation candidate"
  git push origin main
  # 在流水线空闲时安全重启服务，保留所有既有凭证
  ```

---
**交付结论**: 候选 Commit `3054114c91c636fd5833c693c13bd82f015016d3` 现已完全冻结，未执行任何真实验收操作，等待 Codex 独立审查与授权下一步范围。
