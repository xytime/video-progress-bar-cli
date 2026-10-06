# 双语跟唱／跟读流水线：待确认规格

日期：2026-10-07。作者：Codex；精确模型标识未知。状态：**规格草案，尚未批准实现**。

目标：输入本地音频、与音频对应的表演视频、英文及中文文本，生成可复核、可重复渲染的 9:16 双语跟唱／跟读视频。推荐首版为独立制作入口，完成至本地成片和 QA 回执。

交付文件：

- [architecture.md](architecture.md)：系统与依赖图、目录、六个模块、技术取舍、扩展路径与验收。
- [core-design.md](core-design.md)：音频／对齐、断句／运动、编排的接口与算法设计；均非已实现代码。
- [timeline.schema.json](timeline.schema.json)：完整 JSON Schema Draft 2020-12，定义 `follow-along.timeline/1.0`。
- [timeline.example.json](timeline.example.json)：人为构造的数据契约示例，不能作为媒体、对齐或排版成功证据。
- [verification.md](verification.md)：本机事实、Schema/示例与 14 项契约检查的实际结果及限制。

推荐决策：

1. 首发渲染器采用 **FFmpeg + Pillow/FreeType 冻结字形图集**；用单个 FFmpeg 完成视频解码、裁切、合成与编码，Python 只生成文字／遮罩帧。保留独立 `Renderer` 接口，后续可接 Remotion 或 Skia。
2. **已知英文原文 + 分窗 CTC 强制对齐** 为主路线。WhisperX 是首个候选适配器；ASR 只用于获得粗锚点和交叉核验，不用它静默改写歌词。歌声、拖腔和重复段必须单独验收。
3. 人声分离采用 `StemSeparator` 接口，优先允许用户提供 stems；首个本地适配器候选为锁定版本的 audio-separator／Demucs。实际版本、模型与设备在短样本兼容性验证后冻结；不升级生产 venv 试错。
4. 原始母带、对齐人声和最终混音是三个不同产物。默认保留原曲，教学模式可调整人声／伴奏与轻度 ducking。分离伪影不能被“响度合格”掩盖。
5. 自适应安全区、字体大小、断句偏好与音频目标是可配置的推荐值；缺词、非法时间、错误素材映射和真实溢出是阻断条件。

首版边界：

- 新内容类型建议为 `BILINGUAL_FOLLOW_ALONG`；不沿用 `ENGLISH_WORLD_SHORT` 的新闻、语言 QA 或发布策略。现有受众与审批规则需在接入运营队列时另行确认。
- 同一段音视频允许显式偏移；不同演出／录音版本无法自动保证口型对应，进入 `NEEDS_REVIEW`。
- 首版不做中文翻译生成、多人重叠歌声、自动重剪源视频、编辑器双向交换或分布式服务部署；接口保留扩展空间。
- 不把首版入口接入 cron、自动选题、上传、评论或通知。发布是另一项有平台授权和证据账本的工作。
- 不改旧成片、旧 QA、历史投稿或现有生产配置。新增依赖在隔离模型环境中验证，业务执行仍通过项目 venv 与资源守卫。

已核实的事实：当前 checkout 为 `main`；有无关未跟踪工作。已有 `study_cards` 逐词模型、文字布局和 FFmpeg 合成器，但其新闻内容约束不适合直接充当歌唱 AST。本机为 arm64、16 GiB、10 个物理核；项目 venv 为 Python 3.12.4，torch 2.9.1、Pillow 11.3.0、jsonschema 4.26.0；未安装 whisperx、demucs、torchaudio。未加载模型或执行媒体加工。

通过标准：至少一个真实讲话样本和一个真实歌唱样本完成音画对应、双语无缺词、动态安全区、编码后音频与恢复／缓存验证；长音、重复副歌、缺失时间和字体缺字等失败样例必须给出可定位回执。具体门槛见 [architecture.md](architecture.md) 的验收表。

本轮只交付规格和数据契约。Schema 结构验证与示例验证不代表业务语义验证、词级对齐成功或真实成片成功。

确认点：是否按以上首版范围，在本仓库独立命名空间实现本地制作路径，先完成真实样本与资源基准，再评估运营接入？这是用户要求的“先确认规格再开发”约定；[critical-collaboration](</Users/ryusei/.codex/skills/critical-collaboration/SKILL.md>) 明确要求：`Await confirmation before changing product code, dependencies, schema, or runtime for the proposed implementation.` 本目录 JSON Schema 是待批准的规格文件，未迁移数据库或启用运行契约。
