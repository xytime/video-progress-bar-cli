---
name: baiju-guoxi
description: >-
  制作「白驹过隙 / 今昔跨越 / Then & Now」人物主题的照片静态提案、手机竖屏卡片、
  60fps 视频与独立封面。当用户说「白驹过隙做某个主题」时使用；先核实照片和年代，
  借鉴真实配乐案例并提供试听，确认后制作，发布遵守当次授权。
---

# 「白驹过隙」(Baiju Guoxi) 技能固化与泛化生产指南

「白驹过隙」是一套针对高播放量与极高完播率 **“Then & Now / 今昔时光跨越”** 题材打造的标准化二创与母带生成引擎。通过自适应数据配置驱动，已实现对任意人物、题材与主题（如经典传奇乐队、硅谷商业巨擘、体坛常青树、文史宗师等）的**静态提案画板 + 动态 60fps 母带视频 + 视频号专用合规封面 + 全自动化发布**的全链路固化生产。

## 制作入口：先确认画面与实际配乐

- 每次新主题、选曲或替换音乐，先读 [配乐选择与试听规范](references/music-selection.md)。改用 HyperFrames、Remotion 或自编脚本，也必须保留此流程。
- 同一轮提案提供：核实照片和年代的静态图、真实参考案例、通常两条可播放的配乐候选及明确推荐。静态提案获批不代表从未试听的配乐也获批；已有明确选曲授权则直接沿用，不重复询问。
- 配乐的吸引力、时代记忆与音画情绪是创作验收；响度、峰值、时长、音频去重只是技术检查，两者分别记录。不得因「原创、无外部采样、技术检查通过」就认定好听或适合。
- 2026-10-16《算力时代的三张面孔》的程序合成配乐已被用户明确否定，作为失败样本，不作为默认音轨、成功案例或下个主题的配乐模板。本次反馈仅更新技能，不重做或重发旧片。

---

## 1. 核心设计哲学与硬性规范

根据本项目受众画像规范（[`docs/audience_persona.md`](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/docs/audience_persona.md)）及视频号 40+ 高净值人群审美（75.8% 40岁以上、70% 男性、55% iPhone）：

1. **画面呈现（单一全屏人像呈现）**：
   - **严禁同屏同时出现年轻和老两种形象**，彻底杜绝小画框、双脸分屏拼接或同屏左右/上下并置。
   - 每一瞬间画面均为 **100% 满屏单人巨幅肖像**，眼神与岁月痕迹扑面而来。
2. **时光切转（“白驹过隙 · 时光之刃” 电影级光学切转）**：
   - 大光圈抽焦虚化（Defocus）+ 金色横向变形镜头激光流光（Anamorphic Flare Streak）。
   - 切点瞬间重聚焦（Snap-Focus）揭晓数十年后的从容面容。
   - 核心年份与年龄机械高速翻牌滚动，配合平滑金流色谱演变。
3. **微信视频号手机安全区规范**：
   - **顶部安全区**：$Y \ge 225\text{px}$，严格避让手机状态栏、灵动岛、微信返回键与更多按钮。
   - **底部安全区**：$Y \le 1530\text{px}$，严格避让创作者头像、发布文案、点赞/转发/收藏栏及进度条。
   - **视力友好超大字**：88px~96px 黄金大字 + 多重投影浮雕，保证移动端弱光环境下极高可读性。
   - **零缺字豆腐块（0 Tofu）**：采用纯矢量金色星芒（`draw_gold_star()`）与思源宋体，杜绝特殊 Unicode 符号乱码。
   - **无大遮罩局部柔光**：严格遵守视频号封面与版式政策（`no_broad_dark_overlay`），仅在文字区域做局部柔光晕染。

---

## 2. 动态视频节奏与时间节拍公式 (Rhythm & Duration Contract)

以标准 4 人 35.5s 母带为基准，时间节拍完全基于题材配置自适应，通用公式为：

$$\text{Total Duration} = \text{Intro Duration} + N \times \text{Person Duration} + \text{Outro Duration}$$

| 阶段 | 默认时长 | 视觉内容与节奏细节 |
| :--- | :--- | :--- |
| **片头经典封面帧** | **3.0s**（无封面则为 0s） | 初创合影/高光瞬间原版老照片，环境散景延伸（Ambient Bokeh Backdrop），微推镜，96px 粗体年份与标签 |
| **单人展示周期** | **7.0s** / 人 | **青年展示 3.1s**：100% 满屏青年肖像，从容展示经典初啼；<br>**时光之刃 0.8s**：3.1s~3.5s 抽焦虚化与流光升腾，**3.5s 切点瞬间重聚焦至老年并完成数字翻牌**，3.5s~3.9s 炫光收敛；<br>**老年展示 3.1s**：100% 满屏老年肖像，从容领略岁月沧桑与从容风度 |
| **片尾传世金句卡片** | **4.5s** | “时间从来不语，却回答了所有问题”，黑金悬浮卡片配合末尾缓和暗转淡出，充分回味沉淀 |

**典型题材时长参考**：
- **4 人题材**（如 ABBA、硅谷四杰）：$3.0 + 4 \times 7.0 + 4.5 = \mathbf{35.5\text{s}}$
- **3 人题材**：$3.0 + 3 \times 7.0 + 4.5 = \mathbf{28.5\text{s}}$
- **2 人题材**（双雄对决/师徒传承）：$3.0 + 2 \times 7.0 + 4.5 = \mathbf{21.5\text{s}}$
- **1 人特辑**（人物传记与丰碑）：$3.0 + 1 \times 7.0 + 4.5 = \mathbf{14.5\text{s}}$

以上是画面默认时长，不是音乐天然合拍的证据。选曲后标注实际乐句、重拍与年代揭晓的对应关系；需要调整已确认的画面时长时说明取舍，不能机械循环、粗暴截断或强行变速凑时长。

---

## 3. 系统架构与工程资产清单

本模块遵循仓库单向依赖 DAG 宪法，工程资产分布如下：

```
├── .agents/skills/baiju-guoxi/SKILL.md           # 本技能操作指南与规范
├── src/video_processing/baiju_guoxi/
│   ├── __init__.py                              # 导出核心模型与渲染器
│   ├── models.py                                # DeckConfig, PersonComparison, StrategyCard 数据模型
│   ├── renderer.py                              # BaijuGuoxiRenderer (Jinja2 + Playwright 无头 Chromium)
│   └── templates/
│       ├── presentation.html.j2                 # 16:9 桌面演示文稿多页模板 (PDF + PNG)
│       ├── presentation_vertical.html.j2        # 9:16 视频号竖屏全案演示文稿模板 (PDF + PNG)
│       └── mobile_card.html.j2                  # 9:16 移动端单人物海报卡片模板 (1080x1920 PNG)
├── scripts/
│   ├── generate_baiju_guoxi.py                  # 静态 PPT 提案与移动端卡片生成 CLI
│   ├── render_baiju_guoxi_video.py              # 60fps 动态流转视频渲染器 (自适应母带音轨与文本)
│   └── generate_baiju_guoxi_cover.py            # 微信视频号 6:7 / 1:1 专用合规封面与来源凭证生成
├── assets/baiju_guoxi/
│   ├── abba/                                    # 实战样板 1：经典乐团 ABBA (已成功发布入库)
│   └── tech_titans/                             # 实战样板 2：硅谷科技四杰 (乔布斯、盖茨、黄仁勋、马斯克)
└── tests/unit/test_baiju_guoxi.py               # 自动化沙箱隔离测试套件 (100% 覆盖)
```

---

## 4. 如何为新题材一键生产「白驹过隙」作品（最佳实践操作手册）

### 第一步：创建题材素材目录与准备照片

在 `assets/baiju_guoxi/<topic_id>/` 下建立题材目录，准备以下素材：
1. **片头封面原图**（可选）：合照、初创现场或高光时刻历史原图，命名如 `intro_1976.jpg`；
2. **每位人物对比肖像**：
   - `photo_a`：早年/初创时期的 1:1 纯正人像（无字幕、无台标水印），命名如 `p1_young.jpg`；
3. **背景配乐（先参考、再选段、实际试听）**：
   - 按 [配乐选择与试听规范](references/music-selection.md) 建立参考与候选；用户以前肯定的作品优先作为比较基准，不能擅自认定某条旧片就是用户所指的「上一次」。
   - 历史目录中的港片、Queen、世界杯歌曲可作为时代记忆与标志乐句的研究样本；不能仅凭知名曲名或「史诗、科技、合成器」标签选曲，不能把已有文件当作成功证据或直接发布授权。
   - 不从其他主题复制音乐充当占位符；保留现有跨题材 MD5 检查及显式共享配置。原创音乐可以进入候选，但不默认用简单程序合成的循环脉冲、和弦铺底、扫光声代替有旋律和情绪起伏的音乐。
   - 登记 `audio_title`、`audio_artist`、`audio_theme_match`、`audio_segment_desc`；另将参考、试听、使用依据、用户选择和最终音轨哈希写入本主题的 `music_review.md`。未试听确认时停在音乐提案，继续照片等不依赖音乐的已授权工作。

### 第二步：编写题材配置文件 `<topic_id>_deck.json`

参考通用配置规范（详见下方第 5 节），填写题材主标题、片头说明、人物生平硬核事实（杜绝空洞抒情套话）、点睛金句、专属配乐元数据及视频号封面元数据。

### 第三步：生成静态提案画板，并提供配乐试听

```bash
# 生成 9:16 手机竖屏演示文稿 (8 页 PDF + 8 张 1080x1920 PNG) 及单人卡片
PYTHONPATH=src .venv/bin/python scripts/generate_baiju_guoxi.py \
  --config assets/baiju_guoxi/<topic_id>/<topic_id>_deck.json \
  --output-dir output/baiju_guoxi/<topic_id>
```

将静态提案与配乐参考、可播放的候选试听一起交付，记录用户对实际音轨的选择。不得只展示静态图，再在成片时自行加入未试听的音轨。

### 第四步：一键渲染 60fps 动态视频母带

先检查本主题 `music_review.md` 已记录实际试听确认和选定文件哈希。此要求是代理制作流程检查，当前渲染器不会自动读取该记录；技术测试通过不能替代它。

```bash
# 全自动装配片头、单人轮转、时光之刃切转、金句尾声与母带音轨
PYTHONPATH=src .venv/bin/python scripts/render_baiju_guoxi_video.py \
  --config assets/baiju_guoxi/<topic_id>/<topic_id>_deck.json \
  --fps 60
```
> 输出位置：`output/baiju_guoxi/<topic_id>/<topic_id>_video.mp4`

### 第五步：一键生成视频号专用合规封面与来源清单

```bash
# 全自动生成符合 6:7 推荐流、1:1 主页及 9:16 播放态严格安全区的封面与 cover_provenance.json
PYTHONPATH=src .venv/bin/python scripts/generate_baiju_guoxi_cover.py \
  --config assets/baiju_guoxi/<topic_id>/<topic_id>_deck.json
```
> 输出位置：`output/baiju_guoxi/<topic_id>/wechat_publish/`
> 产物清单：`cover.jpg`、`cover_provenance.json`、`preview_cover_6_7.jpg`、`preview_cover_1_1.jpg`

### 第六步：一键上传发布至微信视频号

```bash
# 通过流水线上传脚本直接发布
.venv/bin/python scripts/wechat_uploader.py \
  --video output/baiju_guoxi/<topic_id>/<topic_id>_video.mp4 \
  --cover output/baiju_guoxi/<topic_id>/wechat_publish/cover.jpg \
  --title "【白驹过隙】<主标题> | 跨越半世纪岁月回眸"
```

---

## 5. 标准通用 JSON 配置文件 Schema 字典

```json
{
  "issue_tag": "白驹过隙 · 第 02 期",
  "series_title": "商业与科技传奇 · 时代巨浪",
  "project_meta": "PROJECT: TECH TITANS / 50-YEAR CHRONOS RETROSPECTIVE",
  "pre_title": "CHRONOS & SILICON VALLEY ARCHIVE",
  "main_title": "硅谷四杰 · 跨越半世纪的科技浪潮与容颜对照",
  "sub_title": "1975-2025 五十载光阴 · 重构全球计算与商业文明 · 四位科技巨擘真实容颜对照与生平硬核档案",
  "chips": [
    "💡 个人电脑、图形计算、操作系统与星际探索的奠基者",
    "🏛️ 累计重构全球数万亿美元市值与数字文明生活方式",
    "⏱️ 跨越 50 载光阴 · 从车库意气风发到从容银发丰碑"
  ],
  "footer_text": "六维时空 · 白驹过隙时光档案",
  "include_strategy_slide": true,
  "include_grid_slide": true,
  "include_interactive_slide": true,

  "intro_image": "tech_intro_1976.jpg",
  "intro_title": "硅谷风云 · 1976 初创年代",
  "intro_subtitle": "车库初创与第一代微型计算机诞生高光时刻",
  "intro_year": 1975,
  "intro_label": " · 初创风云",
  "intro_desc": "半个世纪数字文明的起点 · 4位先驱时代回眸",

  "audio_path": "audio_35s.m4a",

  "outro_title": "1975 - 2025 · 半个世纪科技传奇",
  "outro_quote": "“时间从来不语，却回答了所有问题”",
  "outro_sub": "SILICON VALLEY TITANS · 50 YEARS OF INNOVATION",

  "cover_photo": "jobs_1976.jpg",
  "cover_kicker": "白驹过隙 · 硅谷传奇50年",
  "cover_title": "科技四杰 50年面容回眸",
  "cover_subtitle": "“时间从来不语，却回答了所有问题”",

  "persons": [
    {
      "name": "史蒂夫·乔布斯",
      "en_name": "Steve Jobs",
      "role": "苹果公司联合创始人 · 个人电脑与移动互联变革者",
      "year_a": 1976,
      "age_a": 21,
      "desc_a": "21 岁 · 车库初创 / 制造 Apple I",
      "photo_a": "jobs_1976.jpg",
      "year_b": 2011,
      "age_b": 56,
      "desc_b": "56 岁 · 传奇谢幕 / 发布 iPad 与时代丰碑",
      "photo_b": "jobs_2011.jpg",
      "milestones": [
        "1976 年（21 岁）：与沃兹尼亚克在车库创立苹果，推出 Apple I 与 Apple II 开启个人电脑革命。",
        "1984 年（29 岁）：发布首款具备图形界面与鼠标的 Macintosh 电脑，重构人机交互历史。",
        "1997 年（42 岁）：重返苹果力挽狂澜，相继推出 iMac、iPod 与 iTunes 重塑全球音乐产业。",
        "2007 年（52 岁）：发布革命性 iPhone，重新定义智能手机，带领苹果登顶全球最高市值公司。"
      ],
      "bio": "创立苹果与皮克斯，以 Macintosh、iPod、iPhone 重新定义个人计算、数字音乐与移动互联网。",
      "quote": "“活着就是为了改变世界，难道还有其他原因吗？”",
      "key_works": ["《Macintosh》(1984)", "《iPhone》(2007)", "《iPad》(2010)"]
    }
  ],

  "interactive": {
    "badge": "INTERACTION & SILICON VALLEY MEMORY",
    "title": "跨越半世纪科技浪潮<br>哪位先驱的哪一刻最触动你？",
    "question": "“从车库敲击代码到星舰划破苍穹，五十载光阴彻底重构了我们的生活。哪一个瞬间最让你震撼？”",
    "options": [
      {"key": "A", "text": "1984 乔布斯从手提袋取出第一代 Macintosh 的惊艳瞬间"},
      {"key": "B", "text": "1995 盖茨发布 Windows 95 让 PC 走进全球千家万户"},
      {"key": "C", "text": "2006 老黄力排众议坚持 CUDA 豪赌 AI 算力纪元"},
      {"key": "D", "text": "2024 马斯克星舰筷子精准夹住超重型助推器的奇迹"}
    ],
    "callout_highlight": "在评论区写下你人生拥有的第一台科技数码产品",
    "callout_text": "岁月悠长，感谢曾点亮过我们好奇心的每一位科技先驱 · 敬时代，敬岁月"
  }
}
```

---

## 6. 自动化测试与质量守门

修改渲染器、模型或模板时，通过仓库受限隔离沙箱测试；仅修改本技能文档时校验技能格式、引用及操作流程，不为此重渲染已发布视频：

```bash
# 运行单元测试与 Playwright 浏览器及视频生成冒烟测试
.venv/bin/python scripts/run_isolated_tests.py --browser -- -v tests/unit/test_baiju_guoxi.py
```

沙箱测试对以下指标进行严苛守门：
- **画幅覆盖率**：双图占比 100% 满屏覆盖（> 90% 红线）；
- **字号易读性**：大字号 $\ge 80\text{px}$（竖屏 88px，横屏 96px），自适应防溢出（标题字号支持向下自适应至 36px）；
- **安全区规范**：$Y \ge 225\text{px}$ 且 $Y \le 1530\text{px}$；
- **时光之刃切转**：光学抽焦切转窗口对齐、零面孔黑斑遮挡，人物切转前后 0.25s 对称平滑淡入淡出；
- **全案时间跨度闭环**：多人物题材（如乔布斯 35 年 vs 盖茨 50 年）统一采用全案 `max_time_delta` 与 `earliest_year - latest_year`，杜绝首人跨度误导全景谱；
- **多题材自适应**：无 ABBA 特定文本泄露，自适应时长时间轴对齐；
- **原声音轨防护**：无论外部配乐长短，均通过 `-stream_loop -1` 防止母带提前截断，并在尾声 1.0s 执行平滑音画同步淡出；
- **专属场景配乐合规闸门**：跨题材音频 MD5 零冲突（严禁复用与复制），音量必须处于有效声压区间（mean_volume >= -45dB），配置文件严格包含场景契合元数据；
- **配乐创作验收另行确认**：真实案例对照、实际选段试听、用户选择与最终音轨哈希按 `music_review.md` 记录；上述音量和去重测试不证明音乐有吸引力；
- **来源清单与合规政策**：`cover_provenance.json` 自动生成且符合 `no_broad_dark_overlay`，非 ABBA 题材严格 Fail-Closed。
