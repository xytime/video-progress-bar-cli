# 阶段资源槽并行与插队（boost）

作者：Grok Bot。2026-11-06。

## 行为

- `enable_stage_resource_slots=true`（默认）时：加工不再整段独占 `output/pipeline.lock`，按阶段申请资源槽；拿不到槽则**非阻塞回队 PENDING**，禁止假 PROCESSING 死等。
- `enable_stage_resource_slots=false` 时：回退历史「整片 pipeline.lock」串行。
- 同视频 `task_locks/{id}.lock`、发布/WeChatSessionLock、MarketGuard、维护 gate 不变。
- FFmpeg 进程级限流仍由 `ffmpeg_slots` + `GuardedPopen` 执行（默认 1）。

## 配置（后台可改，热生效）

唯一文件：`~/Library/Application Support/VideoProcessing/ffmpeg-slot/resource-limits.json`

```json
{
  "ffmpeg_slots": 1,
  "enable_stage_resource_slots": true,
  "stage_slots": {
    "download": 1,
    "copywriting": 2,
    "asr": 1,
    "ffmpeg": 1,
    "cover_local": 1,
    "agy_image": 1,
    "asr_ffmpeg_combined_max": 2
  }
}
```

- Dashboard「⚙ 资源槽」或 `GET/PUT /api/resource-limits` 可改。
- **热生效**：每次名额申请重读该文件；无需重启进程。非法值回退默认，不放开无上限。

## 插队 boost

- 字段 `processed_videos.queue_boost_at`（REAL，可空）。
- `POST /api/videos/{id}/boost`；待处理/处理中「⏫ 插队」。
- 选片 `ORDER BY` 最前按 boost；**不 preempt** 正在持槽的重型任务。
- 与微信发布 `recovery_priority` 无关。

## 回滚

1. 后台关闭「启用阶段资源槽」，或把 JSON 里 `enable_stage_resource_slots` 设为 `false`。
2. 或 `git` 回退本提交并维护 adopt。
