# 人工普通话译制：频道音色档案与火山声音复刻

## 目的与边界

本档案库为人工普通话译制提供“源频道 → TTS 音色”的可审计选择。它不属于 `PipelineManager`，不会让发现、评分、日常重试、发布窗口或平台投递自动领取译制任务。

当前唯一专属档案是：

| 档案 ID | 服务频道 | provider | 模型资源 | 声音 ID |
| --- | --- | --- | --- | --- |
| `volc_wall_street_truthbombs_mandarin_v1` | 《华尔街真相炸弹》 `UCTK_cv-y88CScoudcXnS1Ew` | `volc_speech` | `seed-icl-2.0` | `S_divMm4n62` |

当源频道精确命中该档案时，`./vpanel dubbing create` 的人工译制任务使用该声音复刻音色。其他频道没有匹配档案时，系统保持原有 MiniMax 默认 TTS；不会猜测、借用或静默切换到某个其他频道的复刻音色。

## 配置分层

1. `config/dubbing_voice_profiles.json`：可提交的非密钥档案。保存频道 ID、provider、模型资源、声音 ID、采样率与语速范围。
2. `src/config/settings.py`：所有运行时环境变量的唯一声明处，并注明密钥边界。
3. `.env`：仅本机保存 `VOLC_SPEECH_API_KEY`。该文件已被 Git 忽略，禁止把其内容粘贴到报告、数据库、任务快照或聊天。
4. `.env.example`：仅保留空值与说明，供新机器初始化。

任务创建时会把实际选中的档案快照写入 `dubbing_jobs.config_json`，并持久化 provider/model/voice ID。快照不包含 API Key，因此修改未来档案不会改变已经创建的译制任务。

## 新增一个频道专属音色

1. 在豆包语音控制台为目标频道准备并验收专属声音复刻音色。
2. 把同一豆包语音项目的专用 Key 仅写入本机 `.env` 的 `VOLC_SPEECH_API_KEY`。
3. 在 `config/dubbing_voice_profiles.json` 的 `profiles` 数组追加一个条目；每个 `channel_ids` 必须只属于一个档案。
4. 固定 `provider="volc_speech"`、对应 `model`（复刻 2.0 为 `seed-icl-2.0`）及 `voice_id`。`sample_rate` 可选 8k/16k/22.05k/24k/32k/44.1k/48k。
5. 运行档案单元测试；随后只对一条已发布源片执行 `./vpanel dubbing create <YOUTUBE_ID>` 做试听、字幕和时长验收。创建不发布；发布仍需要单独 `approve` 与 `publish --confirm`。

## 失败策略

- 匹配到多个档案、档案格式损坏、未知 provider：拒绝任务，不回退，以避免音色串台。
- 频道没有档案：只回退既有 MiniMax 默认 TTS。
- 命中火山档案但没有 `VOLC_SPEECH_API_KEY`，或服务端拒绝权限：任务失败并保留服务端 logid；不降级到其他频道音色。
- 同一文本、档案、语速与采样率命中本地缓存时不再请求 API，避免重复计费。

## 运维提示

火山声音复刻 2.0 不使用 SSML；传入纯文本。API Key 一旦泄露应在豆包语音控制台轮换，并只更新 `.env`。轮换不会改变音色档案或历史任务快照。
