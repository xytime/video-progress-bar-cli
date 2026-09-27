# agy CLI 示例与封面故障验证

日期：2026-09-27（Asia/Shanghai）。作者：Codex。

本机 `agy --help` 与 `agy models` 已核对。下列模型 `gemini-3.7-flash-high` 当前可用。
封面备用执行器现走本机 agy CLI；旧 SDK 的 LocalConnection 明确要求 Gemini API Key，不能代表 App/CLI 登录通道的生图配额。

## 1. 一次文字问答（已实测）

```bash
agy --model gemini-3.7-flash-high --mode plan --sandbox \
  --print-timeout 45s --print '不要使用工具，不要读取文件。用三句话解释 CLI 和 API 的区别。'
```

`--print` 运行一次后退出；`--mode plan` 用于调查和规划。

## 2. 按 JSON Schema 返回结构化结果

```bash
agy --model gemini-3.7-flash-high --mode plan --sandbox \
  --output-format json \
  --json-schema '{"type":"object","properties":{"summary":{"type":"string"},"next_step":{"type":"string"}},"required":["summary","next_step"],"additionalProperties":false}' \
  --print-timeout 45s \
  --print '不要使用工具。描述一个任务：检查封面是否由 AI 生成。返回 summary 和 next_step。'
```

CLI 的外层 JSON 是会话回执（包含 `status`、`response`）；不要把它当成图片成功证据。

## 3. 只读审查一个本地文件

从项目根目录运行：

```bash
agy --model gemini-3.7-flash-high --mode plan --sandbox \
  --print-timeout 90s \
  --print '只读 scripts/run_antigravity_cover_doer.py。检查超时、图片落盘和 OCR 失败处理。不要修改文件，不运行脚本，不联网。最多列出三项有代码依据的问题。'
```

## 4. 生成一张封面底图（已实测落盘）

在独立演示目录运行，避免带入项目生产材料：

```bash
mkdir -p /tmp/agy-telescope-demo
cd /tmp/agy-telescope-demo
agy --model gemini-3.7-flash-high --effort high \
  --mode accept-edits --sandbox --add-dir /tmp/agy-telescope-demo \
  --output-format json --print-timeout 90s \
  --print 'Call generate_image exactly once. Create one original portrait 3:4 editorial illustration of a telescope studying a distant planet. No text, letters, numbers, logos, watermark, UI, screenshot or video frame. Keep the upper-left area quiet for later typography. Save the actual bitmap as candidate.png in the current directory. Return status and asset_path. If generation fails, report the error and never synthesize a placeholder.'
```

交互授权按 CLI 提示处理。项目自动执行器使用 `--dangerously-skip-permissions`，仅用于已授权的隔离生图任务；上面的手动示例不需要它。

本次实测图片为 `output/agy_cli_demos/20260927/telescope.png`，尺寸 896×1200；CLI 回执耗时约 28 秒，OCR 无文字。文字与图片调用回执保存在同目录。示例图片是插画，不是天文观测事实。

两次完整备用执行器实测都成功落盘位图，但严格 OCR 分别读出零散字符而拒收，未写 `result.json`；图片与失败回执也保存在示例目录（`*_rejected.*`）。这证明生成通道恢复及失败闸仍有效，不能证明自动验收可靠性已经收口。相关隔离测试共 35 项通过，概要见同目录 `verification.json`。

## 本次修复范围和限制

- 备用执行器从 SDK 改为 CLI，去除传入的 Gemini/Google API Key 和 Telegram 凭据，避免重新落入 API 项目配额。
- 使用项目 venv；CLI 二进制由现有 `AGY_COMMAND` 配置，模型由 `ANTIGRAVITY_MODEL` 配置。
- 继续要求真实落盘位图、竖版尺寸、OCR 无字、哈希绑定及队列截止时间；退出码为零但没有图片仍失败。
- 既有 Codex 首选、32/34 分钟窗口及固定模板降级策略未改变。两分钟巡检可能在备用窗口末尾才启动，剩余时间不足时仍拒绝图片；若要保证 AI 失败绝不发布，需要另行确认“挂起并告警”的发布策略。
- 不重发四条已提交视频，不覆盖其历史封面或原失败记录。
