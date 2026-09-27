# Review Request — 微信视频号助手自动登录修复 (WX-AUTH-20260927)

## 基本信息
- **工单**: WX-AUTH-20260927
- **执行方**: Antigravity
- **目标主干**: `main`
- **交付 Commit**: `fe34c3e` (`fix(wechat): restore desktop quick authorization and loopback resolution`)
- **基线 Commit**: `3b78402`
- **提交与推送状态**: 已提交并成功推送至 `origin/main`

---

## 1. 根因证据与取舍

经过全链路网络拦截、CoreGraphics 窗口层级枚举与 Apple Vision 离线 OCR 分析，确认导致“空白会话无法自动登录、请求挂起直到超时”的根本原因如下：

1. **模态弹窗层级被过滤 (CoreGraphics Layer 23)**:
   - 网页点击“微信快捷登录”后，桌面微信客户端成功收到了 POST `https://localhost.weixin.qq.com:14013/api/authorize` 请求，并在桌面弹出了原生模态授权窗口（包含“视频号创作平台 申请使用”以及“拒绝”、“允许”按钮）。
   - 该窗口在 macOS CoreGraphics 中的 `kCGWindowLayer` 为 **23**（模态面板层，非普通主窗口的 layer 0）。
   - 原候选代码在 `scripts/wechat_auth_vision.js` 中限定了 `w.kCGWindowLayer === 0`，导致该授权弹窗被直接过滤，`authWindows()` 永远返回 `[]`，报错 `NO_SCOPED_AUTH_WINDOW`。
2. **Apple Vision 对中文字符标称置信度门禁过严**:
   - 原代码 `scripts/wechat_desktop_auth.py` 设置了 `item["confidence"] < 0.85` 的硬性丢弃门槛。
   - 现场实测表明：Apple Vision 对非英文词典的中文长短语（如“视频号创作平台 申请使用”）给出的置信度标称值通常为 **0.5**。
   - 该硬性过滤导致关键判定短语被全部过滤抛弃，`combined` 文本始终无法匹配“视频号创作平台”，判定失败。
3. **透明代理/VPN 环境下的环回解析污染**:
   - 在开启 TUN 虚拟网卡（Clash / Surge 等 Fake IP 地址池）的环境下，系统 DNS 会将 `localhost.weixin.qq.com` 判定为虚拟 IP（如 `172.19.1.39`）。
   - Chromium 虽设置了 `--no-proxy-server`，但缺失强制本地映射规则，可能导致请求被虚拟网卡拦截而无法稳定到达微信客户端监听的 `127.0.0.1` 环回端口。

### 取舍与最终方案
- 放弃了侵入式修改或大模型方案，保持**确定性离线原生方案**；
- 修复 `scripts/wechat_auth_vision.js`：放宽窗口 layer 范围至 `0 <= w.kCGWindowLayer <= 30`，精准接纳模态授权面板；
- 修复 `scripts/wechat_desktop_auth.py`：对上下文文本（“视频号创作平台 申请使用”）采用 `>= 0.3` 置信度，对关键点击动作（“允许”按钮）维持 `>= 0.8` 的高置信度与几何中心必须严格位于文字框内的双重校验；
- 修复 `scripts/wechat_uploader.py`：Chromium 启动参数强制追加 `--host-resolver-rules=MAP localhost.weixin.qq.com 127.0.0.1`；
- 日常恢复链路保持 **0 LLM 调用 / 0 Token 消耗**。

---

## 2. 变更清单与 Scoped Diff

### 修改文件清单
1. `scripts/wechat_auth_vision.js` (新增文件，窗口层级过滤修复)
2. `scripts/wechat_desktop_auth.py` (置信度分层校验与几何匹配)
3. `scripts/wechat_uploader.py` (Chromium 强制本地环回映射)
4. `tests/unit/test_wechat_desktop_auth.py` (单测覆盖置信度边界与单测断言更新)

### 完整提交 Diff
```diff
diff --git a/scripts/wechat_auth_vision.js b/scripts/wechat_auth_vision.js
new file mode 100644
index 0000000..7aa4e4d
--- /dev/null
+++ b/scripts/wechat_auth_vision.js
@@ -0,0 +1,60 @@
+/* macOS 视频号授权离线识别适配器，无网络、无模型调用。
+ * 依赖：wechat_uploader -> wechat_desktop_auth -> 本文件 -> macOS 原生接口。
+ * Modification History
+ * | Version | Date | Author | Description |
+ * | --- | --- | --- | --- |
+ * | 1.0.0 | 2026-09-26 | Codex | 仅可见微信小型候选窗口与 Vision 离线 OCR。 |
+ * | 1.1.0 | 2026-09-27 | Antigravity | 放宽模态面板层级窗口过滤(0<=layer<=30)，适配微信自绘授权弹窗。 |
+ */
+ObjC.import('Foundation');
+ObjC.import('AppKit');
+ObjC.import('CoreGraphics');
+ObjC.import('Vision');
+function authWindows() {
+        var all = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(1, 0)));
+        return all.filter(function(w) {
+            var b = w.kCGWindowBounds, title = w.kCGWindowName || '';
+            if (!w.kCGWindowIsOnscreen || w.kCGWindowLayer < 0 || w.kCGWindowLayer > 30 || !b ||
+                b.Width < 200 || b.Width > 700 || b.Height < 120 || b.Height > 900) return false;
+            if (['WeChat', '微信'].indexOf(w.kCGWindowOwnerName) < 0) return false;
+            var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(w.kCGWindowOwnerPID);
+            if (!app || ObjC.unwrap(app.bundleIdentifier) !== 'com.tencent.xinWeChat') return false;
+            // 主聊天窗口和设置页不进入截图候选；不依赖单纯绿色按钮。
+            return title === '' || ['视频号创作平台', '微信登录', '授权登录'].indexOf(title) >= 0;
+        }).map(function(w) {
+            return {id: w.kCGWindowNumber, pid: w.kCGWindowOwnerPID, bounds: w.kCGWindowBounds};
+        });
+}
...
diff --git a/scripts/wechat_desktop_auth.py b/scripts/wechat_desktop_auth.py
index a5c9fc8..0518be1 100644
--- a/scripts/wechat_desktop_auth.py
+++ b/scripts/wechat_desktop_auth.py
@@ -8,6 +8,7 @@
 # Modification History
 | Version | Date | Author | Description |
 | --- | --- | --- | --- |
+| 1.10.0 | 2026-09-27 | Antigravity | 区分上下文文本置信度(>=0.3)与按钮精确置信度(>=0.8)，适配 Apple Vision 对中文短语的标称置信度。 |
 | 1.9.0 | 2026-09-26 | Codex | 视觉后备改为限定小窗口与离线文字验证；校验坐标、窗口身份及停止期限后才点击。 |
@@ -274,18 +275,23 @@ def _verified_visual_allow_center(image, observations) -> tuple[int, int] | None
     height, width = image.shape[:2]
     lines = []
+    allows = []
     for item in observations:
         try:
             text = re.sub(r"\s+", "", item["text"])
             x, y, w, h = item["box"]
-            if item["confidence"] < 0.85 or not (0 <= x < x+w <= 1 and 0 <= y < y+h <= 1):
+            conf = float(item["confidence"])
+            if not (0 <= x < x+w <= 1 and 0 <= y < y+h <= 1):
                 continue
-            lines.append((text, (x*width, (1-y-h)*height, (x+w)*width, (1-y)*height)))
+            box = (x*width, (1-y-h)*height, (x+w)*width, (1-y)*height)
+            if conf >= 0.3:
+                lines.append((text, box))
+            if conf >= 0.8 and text == "允许":
+                allows.append(box)
         except (KeyError, TypeError, ValueError):
             continue
     combined = "".join(text for text, _ in lines)
     if "视频号创作平台" not in combined or "申请使用" not in combined:
         return None
-    allows = [box for text, box in lines if text == "允许"]
     if len(allows) != 1:
         return None
diff --git a/scripts/wechat_uploader.py b/scripts/wechat_uploader.py
index 2cf8ea2..e39c475 100644
--- a/scripts/wechat_uploader.py
+++ b/scripts/wechat_uploader.py
@@ -3,6 +3,7 @@
 # Modification History
 | Version | Date       | Author                              | Description                                              |
 |---------|------------|-------------------------------------|----------------------------------------------------------|
+| 5.11.4 | 2026-09-27 | Antigravity | Chromium 启动参数强制追加 localhost.weixin.qq.com 本地环回映射，防止透明代理与 TUN Fake IP 阻断桌面快捷登录通信。 |
@@ -1582,6 +1583,7 @@ def run_uploader(
                 "--window-size=1280,800",
                 # [BugFix] 禁用代理，防止 Playwright 走海外节点导致微信异地登录强制掉线
                 "--no-proxy-server",
+                "--host-resolver-rules=MAP localhost.weixin.qq.com 127.0.0.1",
             ]
         )
```

---

## 3. 隔离测试收据

执行命令：
```sh
.venv/bin/python scripts/run_isolated_tests.py --browser -- -q \
  tests/unit/test_wechat_desktop_auth.py \
  tests/unit/test_wechat_quick_login_authorization.py \
  tests/unit/test_wechat_login_recovery.py \
  tests/unit/test_wechat_auto_relogin.py \
  tests/browser/test_wechat_quick_login.py
```
- **隔离测试收据目录**: `/private/tmp/video-pytest-ydcucap2`
- **测试结果**: **39 passed, 2 warnings in 22.63s**（0 失败，0 跳过）
- **覆盖边界**:
  1. 正常与迟到授权轮询；
  2. 桌面未登录时（扫码界面）正确拒绝监听；
  3. 跨域/错误来源 iframe 严格拦截无点击；
  4. 授权过期与取消时停止点击；
  5. Qt 自绘控件 AX 不支持时的严格视觉后备降级；
  6. 共享会话锁与发布优先互斥保护。

---

## 4. 真实端到端空白会话与独立复用验证

进行了两次独立完整的端到端全链路真实验证：

### 第一轮验证证据 (Task ID `task-217`)
- **执行方式**: 全新空白浏览器上下文（无 Cookie、无 storage_state）访问 `https://channels.weixin.qq.com/platform/post/create`。
- **授权耗时**: 7 秒内完成桌面模态识别与“允许”点击，总耗时 20.6 秒。
- **发布页凭据**:
  - `step1_url`: `https://channels.weixin.qq.com/platform/post/create`
  - 页面 DOM 内文件输入框: `<input type="file" multiple="multiple" accept="video/mp4,video/x-m4v,video/*"/>` 计数=1。
- **独立复用凭据**:
  - 启动第二个全新独立浏览器上下文，加载保存的会话，无需登录直接打开 `/platform/post/create`，文件控件就绪，免登复用成功。
- **手机参与情况**: **完全无手机参与（`mobile_involved: false`）**。

### 第二轮独立复验凭据 (AUTH-06, Task ID `task-247`)
```json
{
  "auth_mode": "desktop_visual_automated",
  "mobile_involved": false,
  "step1_success": true,
  "desktop_clicked": true,
  "desktop_result": "CLICKED_VISUAL",
  "step1_url": "https://channels.weixin.qq.com/platform/post/create",
  "step1_file_inputs": 1,
  "state_saved": true,
  "step2_url": "https://channels.weixin.qq.com/platform/post/create",
  "step2_file_inputs": 1,
  "step2_success": true,
  "elapsed_seconds": 21.1
}
```
- **发布页截图证明**: `/private/tmp/step2_reuse_result.png`（OCR 识别确认包含“视频管理/发表动态”、“上传时长8小时内...建议分辨率720p及以上”、“视频描述”、“短标题”等全部官方发布元素）。
- **生产状态更新**: 经双重真实验证成功后，通过原子性临时文件替换已更新至 `output/wechat_state.json`，并打上 `output/wechat_login_at.txt` 时间戳。

---

## 5. 无关工作保护说明

本任务严格遵循工作区与 Git 纪律，对无关工作做到了零污染、零混入：
- 未修改或回退 `src/web/app.py`（保留其他任务的代码与端口逻辑）；
- 未触碰 `scripts/fetch_trending_keywords.py`、热词及 `src/video_processing/topic_clues/`；
- 未碰 `src/web/static/css/dashboard.css` 与 `src/web/templates/index.html`；
- 未向微信联系人发送任何消息，未触发任何业务发稿/发评，未修改业务账本；
- 共享锁 `WeChatSessionLock` 始终遵循发布优先。

---

## 6. 运行采用、运营诊断与回退方法

1. **运行采用说明**:
   - `pipeline_manager` 与 `scripts/run_ready_publications.py` 每次发布均通过 `subprocess` 调用 `scripts/wechat_uploader.py`；
   - 代码提交并推送到 `main` 分支后，当前磁盘已是最新版本，任何后续任务自动加载最新逻辑，无需重启不存在的后台 daemon；
   - 现存生产会话 `output/wechat_state.json` 已更新为本次全新自动授权生成的有效态。
2. **运营诊断入口**:
   ```bash
   # 查看当前桌面微信授权预检状态
   .venv/bin/python -c 'from scripts.wechat_desktop_auth import desktop_auth_preflight; print(desktop_auth_preflight())'

   # 仅检查会话有效性或有界免登
   .venv/bin/python scripts/wechat_uploader.py --verify-only
   ```
3. **回退方法**:
   若需紧急回退，执行以下单行命令即可干净回退：
   ```bash
   git revert fe34c3e -m 1 --no-edit && git push origin main
   ```
   旧会话或需人工扫码时，系统仍受控降级为 `DESKTOP_LOGIN_REQUIRED` 或标准二维码模式。
