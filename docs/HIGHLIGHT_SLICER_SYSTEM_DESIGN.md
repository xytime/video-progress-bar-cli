---
created_by: Gemini_3.7_Flash_High_planning
created_at: 2026-08-20T14:08:00+08:00
version: 1.0.0
---

# # Version History
| Version | Date | Author | Description |
|---|---|---|---|
| 1.0.0 | 2026-08-20 | Gemini_3.7_Flash_High_planning | 初始创建：长视频全自动智能金句切片与多模态二创系统架构设计文档 |

---

# 长视频全自动智能金句切片与多模态二创系统开发设计文档
*(Automated Multi-Modal Video Highlight Slicing & Repurposing System)*

## 1. 系统概述与业务目标

### 1.1 业务痛点
当前自媒体与内容分发团队在运营长视频（如访谈、演讲、播客、纪录片）时，面临极高的人工剪辑成本：
- **发现成本高**：需要人工通篇观看 20~60 分钟视频以寻找具有传播力（爆点、金句、认知冲突）的片段。
- **制作周期长**：从选段、精密切割、转录校对、翻译、9:16 竖屏适配、排版加标题，到封面图设计、文案编写，单条短视频平均耗时 40~90 分钟。
- **AI 视觉伪劣感**：当前多数 AI 自动生图工具容易产生“塑料感/畸变人脸”，无法满足专业科技媒体对封面质感与真实感的要求。

### 1.2 系统目标
构建一套**从长视频 URL 输入到多渠道短视频成品全自动输出**的工程化闭环系统。该系统能够：
1. **自动洞察与智能选段**：通过多模态内容理解算法，自动从长视频中提炼 3~5 个具备独立叙事结构的黄金爆点片段（Highlight Snippets）。
2. **音视频精细对齐与无损切片**：结合词级别（Word-level）时间戳与 VAD（语音活动检测），杜绝“吃字”、“吞音”与“杂音硬切”。
3. **自适应竖屏重构与双语字幕**：支持 9:16 三段式毛玻璃动效、自动标题生成与双语高亮字幕烧录。
4. **确定性美学封面引擎**：采用“AI 抽象概念底图 + 确定性矢量/PIL 排版”策略，杜绝劣质 AI 人脸，产出具备《Bloomberg》/《Wired》质感的杂志级封面。
5. **一键文案与发布资产包生成**：自动产出多平台标题（悬念/反差/数字）、短标题、摘要正文及标签矩阵。

---

## 2. 系统总体架构

系统采用**分层解耦、事件驱动的状态机架构**，严格遵循项目已有的单向依赖 DAG 规范：

```
                           [输入层]
                   YouTube / Bilibili / 本地视频
                              ↓
              [1. Ingestion & Preprocessing]
          yt-dlp (防爬代理池) → 16kHz 音频提取 → 预转录
                              ↓
                [2. Semantic Analysis & Mining]
        WhisperX (Word Timestamps) + LLM (Gemini 3.1)
         → 爆点评分模型 (Virality Scorer) + 语义边界初筛
                              ↓
             [3. Audio-Visual Precision Snapping]
       Silero VAD + 能量零交叉检测 → 精准边界矫正 [Start, End]
                              ↓
               [4. Automated Rendering Engine]
     ┌────────────────────────┼────────────────────────┐
     ↓                        ↓                        ↓
[横屏双语原画版]       [9:16 竖屏精修版]       [概念无人物封面生成]
(16:9 + 电影黄ASS)   (毛玻璃背景+自适应标题)  (AI Prompt + PIL排版)
     └────────────────────────┬────────────────────────┘
                              ↓
                  [5. Copywriting & Packaging]
               Gemini 文案矩阵 + 质量审计报告 JSON
                              ↓
                         [输出与分发]
                Video Channels / DB Checkpoint
```

---

## 3. 核心子系统与关键算法设计

### 3.1 智能金句挖掘与爆点评估算法 (Virality Scorer)

长视频不是按固定时间切片，而是基于**语义完整性与传播价值**动态切片：

#### 算法流程：
1. **转录与结构分块**：提取全文字幕，利用 LLM 进行语义段落（Semantic Chunks）划分，保留每段的上下文关联。
2. **多维评分打分卡（0~100 分）**：
   - **认知冲突度 (Conflict Index, 权重 30%)**：是否存在反常识观点、尖锐反问（如“文字能灭火吗？”）。
   - **独立成篇性 (Self-Sufficiency, 权重 25%)**：脱离原长视频上下文后，观众是否能无障碍理解。
   - **金句爆发力 (Punchline Density, 权重 25%)**：是否有高度概括、利于二次传播的格言警句。
   - **情绪张力 (Emotional Valence, 权重 20%)**：语调起伏与情感共鸣度。
3. **候选过滤**：筛选评分 $\ge 80$ 分且时长在 $30\text{s} \sim 90\text{s}$ 之间的 Top 3 片段。

---

### 3.2 语音边界精准对齐算法 (Audio Precision Snapping)

> **教训复盘**：今天测试中出现的 `00:01:52` 截断导致末尾丢失两个单词，核心原因是纯文本时间戳没有考虑说话人的音素尾长（Phoneme tail）及房间混响。

#### 解决方案设计：
```python
def snap_clip_boundaries(
    audio_wav: str, 
    raw_start: float, 
    raw_end: float, 
    word_timestamps: list[dict]
) -> tuple[float, float]:
    """
    结合词级时间戳与 VAD 能量检测，实现智能吸附与自然停顿延展
    """
    # 1. 查找离 raw_start / raw_end 最近的完整句子首尾单词
    start_word = find_first_sentence_word(word_timestamps, target_ts=raw_start)
    end_word = find_last_sentence_word(word_timestamps, target_ts=raw_end)
    
    # 2. 获取基准时间
    snapped_start = start_word['start']
    snapped_end = end_word['end']
    
    # 3. 前置预留（前导静音 0.2s，避免吞掉第一个辅音爆破音）
    final_start = max(0.0, snapped_start - 0.20)
    
    # 4. 后置延展（VAD 尾音检测 + 自然衰减 0.6s~1.2s）
    # 如果紧接着有主持人简短应答（如 "Mhm"），包含在内或平滑淡出
    final_end = snapped_end + calculate_natural_decay(audio_wav, snapped_end)
    
    return final_start, final_end
```

---

### 3.3 视觉构图与竖屏重构引擎 (Vertical Layout Engine)

针对 16:9 横屏转 9:16 竖屏（1080×1920）：
- **背景层**：原视频高斯模糊（`scale=1080:1920,boxblur=20:10`）作为动态磨砂底，提供色彩环境沉浸感。
- **主体层**：居中放置原比例 1080×607 画面，上下留白用于排版。
- **标题层**：顶部黄金视觉区渲染两行大字：
  - Line 1: 白底半透明描边（分类/人物锚点，如 `AI教母：`）
  - Line 2: 荧光黄高亮核心悬念（如 `文字能灭火吗？`）
- **字幕层**：底部 `PlayResY=1920` 坐标系，采用中英双语 Tag-Aware 排版，杜绝生词标签断行。

---

### 3.4 纯概念无人物封面生成引擎 (No-Face Cover Engine)

> **设计原则**：**“严禁生成假脸，只做概念隐喻与大字排版”**。

#### 流程分步：
```
[LLM 提取核心隐喻]
       ↓
[生成无人物英文 Prompt] → (例: "cascading code dissolving into real water and flames, no people")
       ↓
[Image Generator API] → 产出 3:4 / 1:1 8K 超高清科技概念底图
       ↓
[Deterministic PIL Renderer] → 
   1. 居中裁切至 6:7 (1080×1260) 视频号标准比例
   2. 注入顶部 280px + 底部 580px 双向微光渐变暗角
   3. 叠加金线胶囊标签 + 超大粗体描边主标题 + 副标题 + 身份金线
       ↓
[产出高一致性高质感封面]
```

---

## 4. 当前短板与技术挑战（待解决问题）

在今天的实际工程落地中，暴露了以下核心技术瓶颈与改进空间：

### 🚨 短板 1：视频源获取的风控与反爬脆弱性
- **现状**：YouTube 对机器人防护极为频繁（n-challenge、GVS PO Token、403 Forbidden）。
- **待解决方案**：
  - 引入动态 Cookie 池与客户端指纹轮换机制。
  - 构建本地轻量浏览器（Playwright Headless）获取最新 Session PO Token。
  - 增加 Bilibili / 本地文件直接传入等多输入源适配。

### 🚨 短板 2：说话人追踪与动态构图缺失（Speaker Auto-Framing）
- **现状**：目前竖屏化采用固定等比居中，如果长视频中镜头切为偏左或偏右的单人近景，容易造成主体偏离视觉重心。
- **待解决方案**：
  - 引入轻量级 Face/Person Tracking（如 MediaPipe Face Mesh 或 YOLOv8-pose）。
  - 实现平滑镜头平移（Virtual Camera Pan & Smooth Crop），确保说话人始终处于画面中心。

### 🚨 短板 3：长视频 Whisper 转录的计算开销与分词精度
- **现状**：Whisper `small` 模型在 CPU 上处理 25 分钟音频需 1~2 分钟，若处理 2 小时视频开销较大；且原生 Whisper 的断句时间戳粒度不够细。
- **待解决方案**：
  - 接入 `WhisperX` 或 `Faster-Whisper`（CTranslate2 加速），实现 4x 以上提速。
  - 引入强制对齐模型（Wav2Vec2 alignment），获取字符/单词级严格时间戳。

### 🚨 短板 4：文案安全合规与敏感词预审（Censorship Integration）
- **现状**：当前金句切片直接输出文案，尚未与主项目的 `validators/censor.py` 政策敏感词库打通。
- **待解决方案**：
  - 在生成标题与描述后，自动接入视频号平台违禁词字典与敏感政治/广告法检测，违规词自动触发改写（Rewrite Loop）。

---

## 5. 模块开发拆解与实施路线图 (Roadmap)

| 阶段 | 模块 | 核心工作项 | 周期预估 |
|---|---|---|---|
| **Phase 1** | **Highlight Extractor** | 开发 `src/video_processing/processors/highlight_miner.py`：基于 LLM 的长视频分段评分模型 | 2 天 |
| **Phase 2** | **VAD & Snapping** | 实现基于词级时间戳与能量检测的精准断句算法，彻底解决吃字问题 | 1.5 天 |
| **Phase 3** | **No-Face Cover Pipeline** | 封装 `src/cover/concept_cover_engine.py`，实现概念底图生成+矢量排版微服务 | 2 天 |
| **Phase 4** | **Pipeline FSM 集成** | 在 `PipelineManager` 中新增 `HIGHLIGHT_JOB` 模式，支持一键长拆多短视频 | 1.5 天 |
| **Phase 5** | **Web 控制台与一键发布** | 在 FastAPI Dashboard (端口 8765) 增加「智能切片工作台」标签页与可视化微调 | 2 天 |

---

## 6. 接口设计契约 (API Contract)

### 6.1 CLI 统一调度入口
```bash
# 对长视频执行全自动金句切片与二创打包
python -m cli.main auto-highlight \
  --input "https://www.youtube.com/watch?v=ITxsc3mgqts" \
  --max-clips 3 \
  --target-ratio 9:16 \
  --cover-style editorial_no_people \
  --output-dir output/highlights/
```

### 6.2 交付产物清单规范 (`manifest.json`)
```json
{
  "source_video_id": "ITxsc3mgqts",
  "clips": [
    {
      "clip_id": "clip_01",
      "timestamp_range": ["00:01:07.000", "00:01:55.000"],
      "virality_score": 92.5,
      "core_quote": "Can words put down fires?",
      "artifacts": {
        "video_vertical": "output/highlights/clip1_vertical.mp4",
        "video_landscape": "output/highlights/clip1_landscape.mp4",
        "cover_image": "output/highlights/cover1.jpg",
        "ass_subtitle": "output/highlights/clip1.ass"
      },
      "copywriting": {
        "main_title": "ChatGPT已经不够了！AI教母李飞飞一句话反问惊醒所有人",
        "short_title": "文字能灭火吗？",
        "description": "当整个科技界都在加码大语言模型时...",
        "tags": ["AI", "李飞飞", "世界模型"]
      }
    }
  ]
}
```
