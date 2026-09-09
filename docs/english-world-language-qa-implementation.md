# 英语世界语言质检：实现与验收记录

日期：2026-09-09。隔离分支：`codex/english-world-language-qa`。

## 结论与上线边界

已实现 AGY CLI 优先的语言质检链，并完成今天素材的独立审校、一次修订复审、本地渲染与成片音频核验。新增链路没有付费 API 回退。生产开关默认关闭；没有修改历史成片、补写历史 PASS、触发投稿或重传。

**尚未达到生产上线条件。** 以下项目必须继续完成，不能用绿色单元测试替代：

- 今天素材由用户人工复核，特别是原声、全文中文、词性、语境义及音标。
- 连续三次独立生产任务的影子验证；今天同一素材的两个版本和一次缓存命中不算三次。
- 独立基准的人工标签确认，以及语音/音标专项质量验收。目前真实模型基准覆盖文本语义，并非七类检查的全面准确率证明。
- 生产空闲时合并、同步技能及配置，再启用开关。当前不合回生产 main、不更改运行中的每日任务。

## 今天原始素材在哪里

原始目录：`/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output/study_cards/2026-09-09/xsfUZ55Yv-M`。

- 来源：[ABC News 原视频](https://www.youtube.com/watch?v=xsfUZ55Yv-M)。
- 原始视频：上述目录的 `source.mp4`；原字幕：`source.en-orig.json3`。
- 源视频约76.161秒，本次教学片段为源时间7.919–62.320秒，54.401秒，172个英文词、4个段落。
- 原始视频 SHA256：`90fd5957e9b96366a43915c886edfd10e7743aec3d51ae27564d9b02909b610c`。

隔离验收目录：`/Users/ryusei/.codex/worktrees/132c/Video-precessing/output/english_world_language/shadow-20260909`。

当前有效成片是 `shadow-revised.mp4`，不是已被修订替代的 `shadow.mp4`。当前配套文件为 `timeline.json`、`display_plan.json`、`editorial_changes.json`、`shadow-revised.manifest.json`、`qa/language_qa.json`、`qa/source_evidence.json` 与成片音频报告。原始 raw/enriched 副本保存在 `original_timeline_raw.json` / `original_timeline_enriched.json`，没有覆盖历史数据。

## 已确认的故障传播链

| 环节 | 实际证据 | 改造 |
| --- | --- | --- |
| JSON3解析 | 原字幕已有 `15year-olds`、`13th`、`27th`，临时解析正则将其截坏；不能全部归因于 YouTube | 正式解析器保留多词片段、数字后缀、连字符、重复与重叠证据；不虚构逐词时长 |
| 词典匹配 | 词典首义及首词性被当作语境教学义，检索 confidence 不是语义正确概率 | 离线词典提供等级/音标/义项；独立出现位置学习点提供语境义 |
| 词汇展示 | 旧元数据17个“selected”不等于22个微笔记，右栏实际18次/15个去重词 | 展示计划冻结微笔记及右栏；manifest分开记录各口径 |
| 质量门 | 结构/Whisper正确不能证明中文和词义正确 | 七类独立语言检查，覆盖缺失、UNCERTAIN和P0/P1均阻断 |
| 二次文案 | 渲染固定宣传语曾残留“8000词汇量/30s” | 固定展示文案也进入审校；改为A2–B1定位和无固定时长宣传 |

原成片右栏逐屏是：① critical/global/plunged/sobering/measuring；② scores/system/gap/mostly/performance；③ overall/ranks/scores/system/challenging；④ challenging/engaged/behind。`key` 的错误候选未进入旧右栏，不能把候选错误直接等同成片错误。

## 新工作流与代码定位

```text
原始JSON3与选定源片段（保留不变）
  → 确定性解析 + 本地Whisper全片对照
  → Codex按版本协议生成英文修订、完整段译、语境学习点
  → 离线词典证据绑定 + 本地预检
  → 冻结display_plan（正文、微笔记、右栏、固定文案、投稿载荷）
  → AGY独立审校 → 本地覆盖/等级/指纹门禁
       失败：最多一次内容修订并复审；未解决则停止
  → 只消费冻结内容的渲染器
  → 音频、结构、关键帧检查
  → 交付/宿主封装/提交前再次验证绑定
```

| 职责 | 维护文件 |
| --- | --- |
| JSON3解析、差异、真实ASR锚点 | `src/video_processing/study_cards/caption_evidence.py` |
| Codex生成协议 | `docs/english-world-language-generation.md` |
| 离线词典证据与词形音标 | `src/video_processing/study_cards/learning_dictionary.py` |
| 逐屏冻结、密度、布局 | `src/video_processing/study_cards/display_plan.py` |
| 七类Schema、覆盖、指纹、下游验证 | `src/video_processing/study_cards/language_qa.py` |
| 独立Prompt、持久预算、锁、缓存 | `src/video_processing/study_cards/language_review_service.py` |
| 后续投稿文案专项审校 | `src/video_processing/study_cards/publication_qa.py` |
| 命令行编排 | `scripts/english_world_language.py` |
| 可重复影子素材与真实模型基准 | `scripts/english_world_shadow_fixture.py`、`scripts/english_world_language_benchmark.py` |
| 渲染/音频/交付/投稿门禁 | `renderer.py`、`qa_integrity.py`、`english_world/package_integrity.py`、`scripts/notify_english_world_review.py` |

七类检查：TRANSCRIPT_ACCURACY、TRANSLATION_ACCURACY、VOCAB_POS、VOCAB_CONTEXT_MEANING、PROPER_NOUNS_NUMBERS、SEMANTIC_CONSISTENCY、VOCAB_PRONUNCIATION。审校不接收生成器自评分；本地计算最终状态，不照抄模型总分。

调用采用现有受限 `run_agy_structured`，固定 `gemini-3.8-flash-high`、180秒超时。主审校与增量文案共享持久预算：最多3次尝试、1次暂时故障重试、1次内容修订；鉴权/模型错误不回退API。缓存绑定内容、模型和版本，同键并发合并；命中不改写原审校报告，避免使已生成manifest无故失效。纯路径变化重新绑定文件但不重复推理。

## 今天修订版实际教学内容

| 学习点 | 词性 | 语境释义 | 0-based出现索引 |
| --- | --- | --- | --- |
| critical | adj. | 重要的 | 22 |
| sobering | adj. | 令人警醒的 | 35 |
| average | adj. | 平均的 | 38 |
| plunged | v. | 骤降 | 44 |
| mostly | adv. | 基本上 | 52 |
| performance | n. | 表现 | 72 |
| gap | n. | 差距 | 84 |
| ranks | v. | 排名 | 108 |
| overall | adv. | 总体上 | 110 |
| challenging | adj. | 困难的 | 148 |
| behind | adv. | 落后 | 159 |
| engaged | adj. | 投入的 | 167 |

共12个去重学习点，逐屏5/3/3/3个，右栏14次/12个去重词。`ranks` 的词元音标明确标注 `rank`；不把词元音标冒充展示词形音标。增量封面目前拒绝无法明确显示词元标签的这类条目。

## 已取得的验证与成本证据

- 今天首次审校64项通过；一次修订后65项通过，剩余仅P2表达建议。全片本地ASR没有自动改写字幕，US/U.S.等排印差异单独记录。
- 修订成片的音频与绑定验证通过。末词 `age` 约在53.68–53.92秒被识别，成片54.401秒；这是现有0.75秒容差下通过，不能宣称达到更严格的0.18秒尾部标准。
- 真实AGY文本语义基准：10条历史片段、51个学习点、20个标注错误、10个正确对照；20/20错误拦截，0/10正确样本误拦截。标签在调用前冻结，但尚未经过人工独立确认。
- 基准证据目录：`output/english_world_language/benchmark/0596e74b29af6de6b7da750b859cda241e3ae4b3a4f71543d93c72bcdb42bf45/`，包含输入来源绑定、供应商响应和报告。
- 单元测试覆盖解析、数字范围、语境、词形音标、覆盖缺失、旧报告/篡改、缓存失效、并发、CLI故障和共享次数上限。全量隔离测试：**1598 passed，30 subtests passed，12 warnings**，退出码0；证据 `/private/tmp/video-pytest-r21wnskc/pytest.log`。此前一次全量运行的1秒协调器超时用例受同时渲染影响失败；未放宽测试，单独及最终全量重跑均通过。
- 渲染中实际暴露出透明层FFmpeg stderr管道堵塞，已改为临时日志文件；只终止了本任务自身的卡住进程，未重启生产。

供应商实际返回的token，不估造价格或节省金额：

| 调用 | 输入 | 输出 | 合计 |
| --- | ---: | ---: | ---: |
| 今天首次主审校 | 55,473 | 50,875 | 106,348 |
| 压缩输入后的修订复审 | 27,662 | 49,223 | 76,885 |
| 独立文本语义基准 | 22,007 | 15,289 | 37,296 |
| 总计 | 105,142 | 115,387 | 220,529 |

复审压缩掉重复正文和词典候选，保留证据摘要及绑定；第三次对今天素材的相同请求实际缓存命中，没有增加审校次数。CLI消耗订阅额度，不等于免费。

## 优先审查与后续工作

1. 用户打开 `shadow-revised.mp4`，逐屏核对上述12个学习点与完整段译，确认是否达到可教学标准；机器PASS不是人工签字。
2. 人工确认基准标签，补齐语音与音标专项独立验收，再运行两个不同生产任务的完整影子链。
3. 三次影子连续通过后，确认生产空闲，合并并同步共享技能；新契约覆盖旧“8条密度/全离线禁模型”规则，旧片保持旧契约。
4. 开关启用后继续沿用原发布授权、去重及平台状态机制。语言失败记制作质量失败，不拉黑有效来源，不重传历史已投稿素材。

版面观察：修订末屏已显示A2–B1定位与正确的engaged语境义，完整中文可读；DATE字段为空、个别中文行首标点属于待优化排版问题，不应混入语义PASS的含义。
