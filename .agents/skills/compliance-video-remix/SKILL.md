---
name: compliance-video-remix
description: >-
  Prepare a source-evidenced financial video remix proposal, require an immutable human approval,
  and produce a vertical video through guarded local entry points. Rules are not a guarantee of platform approval.
---

# 合规二创：先审后制作

将有完整字幕证据的外媒财经内容整理成中文解说提案和原文对照表。所有生成内容视为不可信输入；主机先做结构校验和内容规则检测，再等待人工审核。自动规则不等于语义安全证明，不能宣称“100% 合规”“已净化所有人脸”或“平台审查通过”。

## 两阶段约束

1. 提案阶段只读取来源元数据与带时间证据的字幕，生成脚本及对照表；不下载母片、不调用 TTS、不渲染或上传。
2. 审批绑定独立提案标识、内容摘要、操作者、用途和有效期。修改提案必须重新生成并审批；取消、过期、已领取提案不能再次执行。
3. 提案以 `source=COMPLIANCE_REMIX` 登记，普通自动队列不得领取。独立提案不能覆盖原片任务。
4. 人工审核需核对全文事实、来源时码与拟用镜头中的人物、字幕、台标及敏感画面。模型给出的镜头列表不构成视觉审核证据。
5. Telegram 的批准按钮只授权制作。发布需要独立、明确的发布用途授权及现有发布治理；本整改版本的直接发布适配器若报告未接通，必须停止，不能手动调用旧入口绕过。

## 入口与架构

唯一受支持操作入口为 `scripts/compliance_remix.py`。技能 scripts 仅兼容导出，核心在 `src/video_processing/compliance_remix/`；DAL 在 PipelineDB。核心不反向定位脚本或读取技能资源。封面与发布能力由外层注入，并复用现有系统。

```bash
# 阶段一：需要真实模型调用；仅在用户授权制作提案时运行。
PYTHONPATH=src .venv/bin/python scripts/compliance_remix.py \
  --propose --url 'https://www.youtube.com/watch?v=p8smG9rkQVY'

# 无副作用演练：不调用模型/TTS、不写生产产物，也不领取审批。
PYTHONPATH=src .venv/bin/python scripts/compliance_remix.py \
  --manifest .agents/skills/compliance-video-remix/examples/sample_manifest.json \
  --source-video output/example.mp4 --dry-run
```

阶段二核对完整审核材料后，使用 `--execute --video-id <提案ID> --content-hash <提案摘要> --source-reviewed` 明确批准制作。精确参数以入口 `--help` 与提案输出为准；不得使用原 YouTube ID 猜测提案、替换哈希或伪造已审状态。旧 `--manifest` 路径仅供演练，不能直接生产。

## 前置校验与故障处理

- Schema 必填字段、口播与分句一致、唯一章节索引、有限正时长、镜头范围、卡片时间、路径安全须先通过，再调用 TTS。
- NFKC、不可见/控制字符、分隔符混淆及中英文规则检查覆盖所有最终输出文本；检测异常时停止。
- 无完整字幕、来源证据不足、模型结构不合格、审核缺失时停止，不能拿标题代替全文生成。
- AGY 现有命令的 plan/sandbox 参数不能证明禁止所有工具。未建立可验证隔离前不调用该通道，明确记录降级至现有受限 Codex；不以提示词替代隔离。
- FFmpeg 必须有真实 ass 滤镜；系统版本不支持时尝试 imageio_ffmpeg，均不支持则提前报错。
- 缓存绑定内容与参数指纹并核验实际媒体，不能只检查“文件存在且非空”。B-Roll 按实际时长补足口播。
- 超时清理进程组；已提交或结果未知时停止重传，保留证据供核验。

## 产物与状态

批准制作后可产生竖屏母带、ASS 字幕、口播音频、数据卡片、标准封面及 provenance。`dry-run` 只返回验证结果，不生成上述文件。示例清单为合成测试内容，不能作为实际事实或镜头审核证明。

制作完成、平台受理、审核中、结果未知、公开可见是不同状态。退出码 0、文件生成、Telegram 通知或提交回执都不能单独证明公开视频已发布。真实模型、音色、镜头质量及平台能力需后续获授权后分别验证。

视觉规格保持 1080×1920；字幕 Alignment 8 / MarginV 570；卡片 980×240。字幕必须先原子高亮再 tag-aware 折行。未经审核不能把遮罩/徽标当作消除原片风险的证明。

详见 [操作与验收 SOP](references/SOP_REMIX_WORKFLOW.md)。
