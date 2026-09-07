# 视频号评论区互动建议

文案生成器在既有 Gemini 请求中新增 `engagement_post` 字段，根据视频标题和简介中的具体内容生成讨论背景、A–D 四个不同选项以及证据追问。来源不足时允许留空，不虚构事实，不自动发布评论。

产物保存在 `output/<youtube_id>_engagement.txt`；分片使用 `<youtube_id>_s<slice_index>_engagement.txt`。它与发布正文分开，不传给视频号上传器，也不作为旧文案 checkpoint 的必要条件。生成降级、格式不合格或历史文件缺失均不阻断正常发布。

主流水线按原生平台 ID 回查确认公开后，将建议合并进现有 `Video Published / WeChat` Telegram 消息，只发送一条文本回执。审核中、未绑定、未知状态不发送公开成功回执。建议缺失时在同一回执内注明待补充。

这是主流水线 copywriter 的扩展；独立英语世界制作包的专用生成与回执流程不经过此入口。已有视频不自动重新生成文案或补发 Telegram。建议依据标题和简介，未承诺完整字幕级事实核查，需人工选用。

验证：`PYTHONPATH=src:. .venv/bin/python -m pytest tests/unit/test_engagement_post.py tests/unit/test_copywriter.py -q`（工作树可使用主目录的 venv）。
