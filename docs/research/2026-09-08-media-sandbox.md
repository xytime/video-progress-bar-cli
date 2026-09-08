# 离线媒体沙盒探针

已安装包源码确认 Whisper 以 XDG_CACHE_HOME/whisper 作为默认缓存，并按 _MODELS URL 中的 SHA 校验已有模型。研究未导入业务设置或读取凭据。元数据 SHA 为 79ecbed714783b6230931a3dba6d5da6d386e2d44f9fc27256e4fc72751e1f62；当前已安装 tiny/base 缓存与元数据匹配。约 221 MB 模型逐块复制到一次性根。Playwright 标准缓存目录通过明确环境传入，现有 DragonEyeRenderer 的默认 launch 无需改代码。

探针 /private/tmp/video-pytest-2h280lb_：初次 exit 1 因 Git 忽略 WAV 导致源码快照无音频，未执行 ASR；加入两份原始合成 WAV 后，原沙盒权限不变，两模型完整识别句子并生成真实封面，exit 0 / 6.479s。原始与纠正日志分别保留，不覆盖。该次修正是探针目录增补，正式测试需重新创建完整快照。

正式初次媒体验收 md82y674：6 passed / 2 failed / 1 warning。一项揭示无翻译时空 ASS 仍报成功；另一项揭示紧贴语音末尾的按帧截断输入不适合检查 ASR 尾段。改为明确 0.5 秒静音尾，无生产时间阈值改动。ln1vnwlx 修复定向验收 7 passed；70cm5w2x 覆盖媒体与依赖/边界定向验收通过。最终全量及部署证据以外部 review.md 为准。

安全边界沿用浏览器研究：媒体不新增 Mach/网络/用户目录许可。浏览器保留已审计的 rendezvous 名称例外，不声称是仅本次 PID 许可。测试夹具均为原创合成素材；研报内价格/日期为既有固定样本，不是当前金融结论。系统字体可读，用户字体未映射。

## Version History
| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-09-08 | Unknown_Model_fast | 记录本机依赖契约、失败/成功探针、实际缺陷与证明边界 |
