# Deep Insight Engine 生产接入

作者：Codex；日期：2026-10-06。

## 范围与依赖

默认关闭。基础双语字幕和竖版渲染保持原流程；以完整基础竖版为输入，
生成独立的导读 → 原声高光与两个动态解析浮窗 → 思考总结成片。
增强失败只记录 `[InsightFallback]`，基础成片仍可由原流程消费。

依赖方向：

```text
scripts/copywriter → utils/insight_planner → core/insight_script + config
pipeline_manager → processors/insight_processor → core/tts_engine + core/insight_script + utils + config
```

没有数据库结构变化、反向 scripts 引用、新服务端口或额外环境变量读取。

## 配置与产物

```dotenv
ENABLE_DEEP_INSIGHT_ENRICHMENT=false
INSIGHT_DEFAULT_VOICE=zh-CN-YunyangNeural
```

开启后，字幕基础成片已验证的任务会先校验已有洞察脚本，没有有效脚本时
调用 copywriter 的 `--insight-only --insight-source ... --insight-subtitle ...`。
使用现有文案供应商选择：AGY 或 Gemini。生成依据为完整有时间戳字幕；
缺失字幕、输入过长、供应商失败、Schema 拒绝均回退，不盲猜高光位置。
此独立子命令不改写普通标题、文案和封面文件。

以 `prefix` 为主键（切片为 `youtube_id_sN`）：

| 文件 | 用途 |
| --- | --- |
| `{prefix}_vertical.mp4` | 保留的基础成片，沿用现有字幕完整性和源时长校验 |
| `{prefix}_insight.json` | Pydantic 洞察脚本，兼容交接设计中的字段 |
| `{prefix}_insight_plan.json` | 自动策划来源绑定；源视频、字幕或脚本变化时重新策划 |
| `{prefix}_insight.mp4` | 独立增强成片 |
| `{prefix}_insight.receipt.json` | 输入/输出哈希、音色及目标时长回执，与脚本独立 |

脚本含非空有限长度文字、有限数值时间窗，恰好两个依序、互不重叠且不越界的浮窗。
高光时间以基础竖版为基准，浮窗触发时间以高光起点为零。
手工提供脚本时须确认同一时间基准；无自动策划来源回执的手工脚本仍可消费。

增强回执绑定源视频、脚本、音色和输出哈希。只有回执与媒体均通过才会优先选用增强版；
关闭开关或缺少有效增强缓存时继续使用基础版/既有互动版。
增强版自带尾部思考卡，优先级高于既有 CTA 互动版，二者不叠加。

## 媒体与审查边界

- Pillow 1080×1920；中文字体按思源、Hiragino、PingFang 回退；缺字体、溢出拒绝生成。
- TTSEngine Edge 路径使用配置音色；不引入第二套语音合成实现。
- FFmpeg 30fps、yuv420p、AAC 44.1kHz Stereo；按实际口播时长向上对齐帧边界并补齐音频。
- 动态浮窗淡入淡出；高光视频和原声一起裁切、归零，三段经解码后的 concat 滤镜缝合。
- 输出必须含音视频；总时长误差不超过120ms，音画起点不超过一帧，尾点差不超过50ms。
  30fps 的时间分辨率为33.3ms，不能声称任意1ms级的视频帧精度。
- 所有临时卡片、音轨和分段在私有临时目录；校验后原子写出。失败不覆盖基础成片。
- 管理器沿用受跟踪子进程：策划最多180秒，增强最多1800秒；失败回退，中断继续传播。
- 新增标题、口播、浮窗和尾卡文字并入统一内容审查，制作与独立发布执行者都会读取；
  不依赖字幕审查开关。审查命中沿用原发布阻断，不允许以渲染降级绕过审查。

## 验证与限制

使用标准 `scripts/run_isolated_tests.py`，包括真实 Pillow 和 FFmpeg 合成、
Schema 拒绝、TTS/卡片/编码失败回退、开关关闭、发布选片、缓存绑定和新增正文审查。
真实媒体测试以离线音轨替代联网 TTS，不能证明 Edge/Gemini/AGY 当前可用。
本地成片与测试不证明视频号已接受该二创，也不证明限流解除、推荐流量或事实正确性。
启用前仍应对真实题材的人名、制度权限、归因与结论做内容复核。
