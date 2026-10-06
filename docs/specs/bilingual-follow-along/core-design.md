# 核心接口与算法设计

日期：2026-10-07。作者：Codex；精确模型标识未知。状态：待实现；本文的签名与步骤是非可执行设计稿。

## 1. 音频与对齐接口

| 接口 | 输入 | 输出与保证 |
| --- | --- | --- |
| `AudioPreprocessor.prepare(asset, source_range, profile)` | 本地哈希素材、源区间、采样 profile | original_master、模型输入、probe 与源时间映射；不修改源 |
| `StemSeparator.separate(prepared_audio, model_spec)` | 原始采样/立体声输入、模型/权重/设备参数 | vocals/instrumental artifact、实际设备、原始诊断、delay；也支持 provided stems |
| `CoarseAnchorProvider.locate(vocals, canonical_text)` | 人声、原始英文/行与 occurrence ID | 有序窗口、候选 ASR 词、文本匹配证据；不改 canonical text |
| `ForcedAligner.align(vocals_16k, text_window, offset_map)` | 已知原文的可对齐词形、有限音频窗口 | 每个原词 ID 的 interval/status/score、原始 token/char 对齐；缺词显式返回 |
| `AudioMastering.mix(master_or_stems, mix_profile)` | 冻结声源、gain/ducking/trim | 无损母带、两遍 loudness measurements、actual_processing；不做字幕依赖 |
| `Chunker.resolve(alignment, bilingual_mapping, metrics, policy)` | 词界、双语意群映射、字形宽度 | 不缺词/重词的 cue partitions、候选被选/拒绝原因 |

所有模型接口必须返回全量输入词的结果；不能过滤掉没有时间戳的词以保持“成功”表象。score 按 provider 独立命名解释，阈值需通过样本标定；不把 score=0.9 写成 90% 正确。

### 建议音频／对齐步骤

```text
prepare:
  probe source audio/video; compare declared range with decoded coverage
  verify same recording or require an explicit audio/video time map
  hash input bytes, text and selected range independently
  extract model input with context; preserve timeline offset

separate:
  use provided, verified stems when present
  otherwise execute pinned separator in an isolated model environment
  verify BOTH stems, sample count, delay, finite samples and output hashes
  save raw separation report; free the model before loading alignment model

align:
  convert a copy of vocals to 16000 Hz mono, preserving sample-time mapping
  normalise aligner text with reversible original-word mapping
  obtain rough anchors (manual or ASR evidence) for repeated sections
  align known text within bounded, monotonically ordered windows
  map window-local timestamps -> stem -> source -> output timeline
  retain observed / manually corrected / estimated / missing status
  reconcile overlapping context windows by stable original-word IDs
  if text is missing, a repeat is ambiguous or timing is only interpolated:
      return NEEDS_REVIEW with exact IDs; keep existing successful artifacts
  validate complete canonical token coverage and timing constraints
```

首版 adapter 的 WhisperX 使用路径是 `load_align_model(language_code="en", ...)` 加 `align(segments, ...)`，segments 是已知文本的粗窗口；不强制先把 ASR 输出当歌词。CPU 设备是本机保守起点，真正版本/API 在隔离适配器试验后冻结。不得直接从未来上游主分支安装到生产 venv。

数字如 `2014`、缩写与发音不规则词经可逆规范化映射到 spoken form；原文仍按作者文字显示。一个原词可映射多个 acoustic tokens，取明确观测到的覆盖区间；无声的标点不能伪装成 timed word。英语重音/口语缩略、拖腔词尾与和声必须在原始报告中可回看。

## 2. 双语语义断句

先有英文的完整词序列及可信词界，再决定读者看到的视觉分组。输入原始换行是偏好，不应逼迫长行溢出。

令 `W[i:j]` 为候选词段，排版函数提供 shaped 英文和已映射中文的真实宽高：

```text
feasible(i,j):
  all included word IDs are consecutive in canonical order
  bilingual mapping exists without dropping/duplicating translation content
  longest atomic token/phrase fits available width at readable font size
  both languages fit configured max rows / active-block height

cost(i,j):
  + line_raggedness
  + syntactic_split_penalty  (e.g. split article+noun or phrasal verb)
  + long_duration_penalty    (soft: melisma is allowed)
  + weak_boundary_penalty
  - punctuation_bonus
  - verified_pause_bonus    (pause >= min_silence_duration)

DP[j] = min(DP[i] + cost(i,j)) for feasible(i,j)
```

候选边界来自标点、可选的语法分析与观测到的停顿；没有语法库时有明确 heuristic fallback，记录原因。单个词超过最大宽度时先尝试合理字号下的换行/连字符规则；若仍无法读则 NEEDS_REVIEW，不能截掉单词。

中文依据 `origin_line_id + meaning_group_id + source span` 映射到同一意群；英文跨意群重排时必须验证映射的可拆性。合并原意群可以保留多个译文 span；无法拆的译文只允许在同一双语块中显示，或等待人工给出子句翻译映射。不要用英文词数比去切中文字符。

`max_rows`、字号下限、停顿阈值是 profile 偏好；修改须进入 layout/chunk key。源文本覆盖与完整性是硬条件。原句长于屏幕是布局问题，不是许可缩短实际歌曲音频的理由。

## 3. 时间与排版契约

v1 默认 `T=48000 ticks/s`，区间半开 `[start_tick,end_tick)`。

```text
frame_time(f) = f × T × fps.denominator / fps.numerator
frame_count  = ceil(duration_tick × fps.numerator / (T × fps.denominator))
sample_tick(n,Fs) = round(n × T / Fs)    # 从原始索引换算，禁止逐项累加

timeline_tick = clip.timeline.start
              + (source_tick - clip.source.start) / playback_rate
```

全部换算内部用有理数；整数输出采用已声明的 nearest-half-up，误差在报告中保留。最后一帧 duration 与采样端点独立检查；帧采样时必须 `f<frame_count`，不多算 `t=duration` 的一帧。首版 playback_rate=1；schema 保留有理数速率，非 1 的请求先拒绝，避免只变画面却未变音频/词界。

布局编译结果包含每个 cue 的文档 rect、每个词的一组 glyph rect、英文/中文 row、字体 asset hash、shaping 版本、静态层 rect 和 reading viewport。text offsets 用 Unicode code point 索引，不是 UTF-8 字节或 JavaScript UTF-16 code unit；跨语言实现必须显式转换。字距包含 kerning，视觉溢出检查用 ink bounds 并包含 stroke/shadow，不能单纯 `len(text)*font_size`。

字幕屏幕坐标为 `screen_x = viewport.x + document_x`、`screen_y = viewport.y + document_y - scroll_y`。圆角视频与 header 始终使用屏幕坐标，不接受字幕 scroll。布局验证和渲染消费同一公式，避免验证的是未滚动画面。

Pillow 起步复用现有 FreeType；同一 shaping/字体生成测量与图集，记录 fallback。缺字不可通过 fallback 的存在推定已解决；需要实际 glyph 覆盖证明。[ImageFont 文档](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html)。以后接浏览器渲染时，应消费冻结几何/glyph 图集，或重新用该后端生成和验证 layout；不能把 Pillow 测量当 DOM 的实际框。

## 4. 运动与高亮：绝对时间求值

每个双语块有内容坐标中心 `c_i`，reading viewport 有屏幕中心 `a`。建议 `target_scroll_i = clamp(c_i - (a - viewport.y), lower_scroll, upper_scroll)`，首尾加留白允许接近居中，但完整双语块不得被裁。若距当前位置小于 deadband，则不滚动。大块优先让完整内容可见；不为几何居中牺牲中文。

在 `[t0,t1]` 从 `s0` 移动到 `s1`：

```text
u = clamp((t-t0)/(t1-t0),0,1)
scroll(t) = s0 + (s1-s0) × easing(u)

smoothstep: 3u²-2u³
exponential_out(k): (1-exp(-k×u))/(1-exp(-k)), k>0
cubic_bezier(x1,y1,x2,y2): solve x(v)=u, then use y(v)
```

cubic bezier 不是直接取 `y(u)`。v1 x1/x2 在 [0,1] 且 x1≤x2，以确保容易单调求解；采用二分/有界迭代。每段保留起止值、参数与全局时间，exponential 在端点正规化，无无限渐近/墙钟积分。过渡相交时先把新 `s0` 计算为旧过渡在当前时刻的值，再截断旧过渡；不从旧目标强行跳转。默认不支持 overshoot。

高亮：活动词满足 `start≤t<end`；`progress = clamp((t-start)/(end-start),0,1)`。有可信词界的长音允许 progress 缓慢推进。mask 在 frozen glyph advance 内左到右扫过；跨视觉行按 glyph 顺序分配，不用包围整段的长矩形误涂中文。中文按 cue-level emphasis 显示，不制造中文的音频 progress。

历史/未来行透明度按**空间距离**求值，例如 `alpha = floor + (1-floor)×exp(-k×distance/viewport.height)`，active 提升到 1；上下渐变 mask 截断 reading viewport。profile 可以不同 past/future floor。静音时没有 active word；可保留上一句 subdued、预显示下一句，状态为 REST。音频仍连续。

纯函数入口建议：

| 接口 | 结果 |
| --- | --- |
| `LayoutCompiler.compile(content_timeline, metrics, visual_profile)` | resolved Timeline 与 immutable glyph atlas manifest |
| `MotionPlanner.plan(cues, viewport, policy)` | 有序且不相交的 motion keyframes |
| `TimingResolver.evaluate(resolved_timeline, frame_index)` | active cue/word、scroll、每个 visible cue opacity、glyph highlight masks |
| `Renderer.render(resolved_timeline, master, output_spec)` | staged MP4、工具版本、stage report；不直接写最终成功状态 |

所有 frames 可以任意顺序求值；某个 f 的结果不取决于是否运行过 f-1。关键性质验证：随机 seek 等价、边界只有一个活动词、长音不闪烁、休止不高亮下一句、快速切句位置连续、首尾双语都可读。

每个 target/property 最多一条显式 motion；未定义的 scroll 使用 layer 初值，未定义的 cue opacity 使用空间 falloff。显式 cue opacity 替代 falloff 值，再与 layer.opacity 和边缘 mask 相乘；word.highlight_progress 未指定时由词时间求值，显式指定时替代自动值。主观动效不能改变词是否处于活动区间。host 验证属性范围与 target 类型，例如 scroll 只作用于 lyrics layer。

## 5. 编排接口与错误边界

`FollowAlongPipeline.run(job_spec, target_stage, resume=True) -> RunReceipt`。

job_spec 包含独立 audio/video/text refs、源选段与音画 time map、separator/aligner profile、双语映射、visual/audio profile。`target_stage` 可为 align、resolve、render、package；显式重跑以新参数/阶段版本或 force 某个具名 stage 为依据，不靠删全部目录。

```text
for stage in topological_order(target_stage):
  inputs = collect ONLY this stage's declared dependencies
  key = hash(stage_revision, inputs, relevant_parameters, model/tool_fingerprints)
  lease = claim(stage,key) with a fencing generation
  if a cache manifest exists AND every required artifact verifies:
      record CACHE_HIT; continue
  record WAITING_RESOURCE; acquire required resource budget
  record RUNNING; execute into same-volume temporary directory
  classify result; validate declared output set
  if review is needed:
      preserve evidence; record NEEDS_REVIEW; stop descendants
  if invalid:
      record FAILED with exact reason; apply bounded classified retry only
  else:
      verify lease generation; fsync where required
      atomic-commit artifacts+manifest; record SUCCEEDED
  release resources and ownership in finally

aggregate receipt from verified stage records
require final media QA before exposing LOCAL_PACKAGE_READY
```

缓存 key 示例：

| Stage | 内容依赖 | 相关参数／fingerprint |
| --- | --- | --- |
| prepare | 原始音视频哈希与选段 | time map、声道、采样处理工具 |
| separate | 原音频 model-input 哈希 | separator + weight hash、context/overlap、实际设备/算法模式 |
| align | vocals 哈希、英文原文/规范化映射、粗锚点 | 模型/词表/adapter revision、窗口与语言 |
| chunk | alignment、双语映射、字体测量 | profile 的容量/语义/停顿策略 |
| mix | original 或全部 stems | gain/ducking/trim/loudness、工具 |
| resolve | chunked cues | visual profile、字体 hash、shaping/motion revision |
| preflight | resolved plan + mix | QA policy revision |
| render | resolved plan、源视频、master、图集 | backend/codec/color profile/tool version |
| package | 成片、resolved plan、冻结证据 | 成片 QA policy revision |

QA 规则变化只使相关 QA/其后的接受阶段重新评估；不得让新的 QA 报告冒充旧视频已按新逻辑渲染。根据是否改变画面决定是否重 render。

推荐异常族：`INPUT_INVALID、SOURCE_MAPPING_AMBIGUOUS、DEPENDENCY_UNAVAILABLE、MODEL_INCOMPATIBLE、STEM_INVALID、ALIGNMENT_INCOMPLETE、ALIGNMENT_AMBIGUOUS、TRANSLATION_MAPPING_MISSING、FONT_MISSING、LAYOUT_OVERFLOW、RESOURCE_TIMEOUT、RENDER_FAILED、OUTPUT_QA_FAILED、CANCELLED`。异常 report 包含 stage/key、输入指纹、实际 tool/provider、受影响 ID、attempts、stderr artifact ref、修订入口。

人工修订文件保留 base alignment hash、word/cue IDs、原/新值、理由、作者与版本。改错词界只重算受影响窗口与下游；除非实现已支持子窗口缓存，否则首版诚实报告整个 align stage miss，不能承诺未实现的细粒度复用。

## 6. Schema 之外的语义验证

JSON Schema 可验证类型、范围与阶段字段，不能证明时间序关系、引用存在或实际媒体。宿主还要验证：

- IDs 唯一；资产、字体、styles、tracks、clips、cue/word、motion target 引用无悬空。
- `synthetic_contract_example=true` 的数据只可作契约检查，不得进入正式媒体制作；引用文件与证据缺失必须被独立闸门拒绝。
- 明确且唯一选定 performer/render_master track，源视频的内嵌音轨不默认混入；derived asset 的 parent/source_time_map 完整，延迟补偿不得重复应用。
- interval.end > start；所有 output intervals 在 duration 内；源区间在实际素材内。
- 首版速率为 1；clip 两侧长度及 offset 对应，VFR/采样率处理有证据。
- resolved 的 timed words 都为 observed/manual，有完整证据；manual 不是模型观测，身份来源分开。
- words 合并后的 canonical token sequence 等于作者英文；中文 source spans 覆盖完整且分组不丢失。
- 中文 cue 来源与英文意群映射一致；不从相邻句借翻译；重复段 occurrence 唯一。
- glyph 行号、坐标空间、字体 style 和文字 span 匹配；实际 ink bounds 含 stroke/shadow。
- 同属性 keyframes 按全局时间严格递增、数值类型匹配；first value 与默认状态兼容；scroll 目标在 layer/cue 定义域。
- 每帧运动后，活动完整双语块与 header/video/occlusion 不相撞；相邻非活动行的剪裁是设计允许行为。
- collision_group 仅用于定位与诊断；不能跳过同组所有对象的碰撞。只豁免明确的基底/高亮配对和允许叠加的背景。
- schema PASS 后仍须独立 QA；resolved 字段由生产者写入不是可信的自我证明。

实施后按 `scripts/run_isolated_tests.py` 验证纯函数和故障恢复；模型/真实媒体走显式隔离 media 或专用适配器边界，不能在主 checkout 裸 pytest 或由测试自动下载模型。
