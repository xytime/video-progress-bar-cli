# 【工程工单】Project Runway-CTA 视频号跑道级流光互动转化系统

- **项目代号**：`Project Runway-CTA`
- **创建日期**：2026-09-19
- **修订版本**：v1.2.0（流水线全链路工程实现落地，隔离测试 100% 通过）
- **当前状态**：【已实现待发布】(Implemented - Ready for Staging/Production)
- **目标分支**：`main`（严格遵守单主干单工作区纪律）

---

## 一、背景与目标

为提升视频号竖屏视频（1080×1920）播放过程中的点赞、关注与完播转化率，在视频播放的**黄金认知点**与**尾部转化钩子**自动合成广播级动态交互组件。

### 核心约束（绝对禁止违背）
1. **绝不遮挡双语字幕**：英文字幕位于 `Y=1040~1160`，中文字幕位于 `Y=1160~1260`，词汇拓展卡位于 `Y=1400~1450`。互动组件严格分为“中央视平线胶囊（`Y=820`）”与“左下角物理指引角标（`X=85, Y=1680`）”，中间字幕区必须保持 100% 洁净，严禁绘制横跨字幕的任何连线。
2. **100% 收拢在视频内部**：微信视频号原生头像与关注按钮位于手机物理屏幕左下角（属于播放器外部系统 UI）。视频内组件所有元素（胶囊、流光微标）必须完整位于 1080×1920 画布安全区内，严禁溢出或模拟假关注按钮。
3. **主副动效错峰呈现**：中央胶囊先展现点击动效，延时 2.0 秒后左下角航向标再启动波纹脉冲，持续 2 个周期后优雅淡出。

---

## 二、本地物理资产清单与可复现运行命令

| 资产类型 | 项目内相对路径 | 说明 |
| :--- | :--- | :--- |
| **标准参考样片** | `output/demo/runway_cta_sample_60s.mp4` | 60 秒 1080×1920 完整合成视频（含双埋点与音效） |
| **自包含参考渲染器** | `docs/work_orders/reference_renderer.py` | 修复未定义路径，含字体回退与 `wave` 音频兜底 |
| **标准提示音源** | `assets/sounds/pop.wav` | 双频清脆 Pop 气泡交互音效 |
| **微距动效图** | `docs/assets/runway_cta/option_c_refined_motion.gif` | 左下角角标微距波纹动效（无内置文本箭头） |
| **静态特写图** | `docs/assets/runway_cta/option_c_refined_crop.jpg` | 黑曜石磨砂胶囊微距特写 |
| **埋点 1 动效** | `docs/assets/runway_cta/real_demo_trigger1_motion.gif` | 黄金认知点（00:12~00:17.5）实机动效 |
| **埋点 2 动效** | `docs/assets/runway_cta/real_demo_trigger2_motion.gif` | 尾部转化钩子（00:46~00:51.5）实机动效 |

### 快速复现运行命令
```bash
# 使用默认输入输出运行验证（自动使用 output/-f7evD_gh34_vertical.mp4，自建临时目录并清理）
.venv/bin/python docs/work_orders/reference_renderer.py

# 或指定自定义输入与输出路径
.venv/bin/python docs/work_orders/reference_renderer.py \
  --input output/-f7evD_gh34_vertical.mp4 \
  --output output/demo/runway_cta_sample_60s.mp4
```

---

## 三、动效时序与几何数学规范（已统一）

### 1. 单次触发时序（严格对齐源码，总时长 5.5 秒）
```
时间轴 (t: 0.0s ~ 5.5s)
[0.0s ~ 0.4s]  中央三联胶囊（Y=820）弹性弹出 (scale: 0.7 -> 1.06 -> 1.0, dy: 12 -> 0)
[0.4s ~ 1.0s]  光标移动至“点赞”并点击 (t=0.8s)，触发“+1”粒子浮空消散，触发第 1 声 Pop 音效 (t=0.8s)
[1.0s ~ 1.6s]  光标移动至“关注”并点击 (t=1.4s)，状态切换为“✓已关注”，触发第 2 声 Pop 音效 (t=1.4s)
[1.6s ~ 2.0s]  光标平滑淡出，中央胶囊保持静止展示
--------------------------------------------------------------------------------------------------
[2.0s]         ★ 延时 2.0s 准时登场：左下角黑曜石胶囊 (X=85, Y=1680) 柔和淡入 (alpha 0.0 -> 1.0)
[2.0s ~ 5.2s]  ★ 持续 2 个周期（单周期 1.6s，共 3.2s）：三级 45° 航向微标自上而下逐级光波脉冲
--------------------------------------------------------------------------------------------------
[5.0s ~ 5.5s]  所有组件全局平滑淡出 (alpha 1.0 -> 0.0, dy: 0 -> 20)
```

### 2. 双埋点策略（全片毫秒级音画同步）
- **Trigger 1（黄金认知点）**：
  - 画面时间：`12.0s ~ 17.5s`（时长 `5.5s`）
  - PTS 偏移：`[1:v]setpts=PTS-STARTPTS+12.0/TB[v_ov1]`
  - 音效点 1（点赞）：`12.0s + 0.8s = 12.8s`（FFmpeg filter: `adelay=12800|12800,volume=0.45`）
  - 音效点 2（关注）：`12.0s + 1.4s = 13.4s`（FFmpeg filter: `adelay=13400|13400,volume=0.40`）
- **Trigger 2（尾部转化点）**：
  - 画面时间：`46.0s ~ 51.5s`（时长 `5.5s`）
  - 顶栏钩子：`• 觉得有收获？点赞关注防走丢 •` 全程随胶囊淡入淡出
  - PTS 偏移：`[2:v]setpts=PTS-STARTPTS+46.0/TB[v_ov2]`
  - 音效点 1（点赞）：`46.0s + 0.8s = 46.8s`（FFmpeg filter: `adelay=46800|46800,volume=0.45`）
  - 音效点 2（关注）：`46.0s + 1.4s = 47.4s`（FFmpeg filter: `adelay=47400|47400,volume=0.40`）

### 3. 左下角组件视觉与数学模型（Option C Refined）
- **胶囊规格**：宽 `196px`，高 `54px`，圆角半径 `27px`。
- **材质**：深色黑曜石磨砂玻璃（`rgba(18, 22, 30, 0.95)`），外边框 `1px rgba(255, 255, 255, 0.18)`，顶缘弧线高光 `rgba(255, 255, 255, 0.30)`。
- **内容**：左侧红色圆形加号微标（直径 `30px`，`#FF3040`），右侧居中文字 `关注创作者`（`21px`，白色），**绝无任何内置文本箭头**。
- **三级 45° 跑道微标**：
  - 方向向量：\(\vec{D} = (-\frac{\sqrt{2}}{2}, \frac{\sqrt{2}}{2})\)（指向左下 45° / -135°）。
  - 两翼开角：中轴 45° 拖尾，对称展角 \(\pm 34^\circ\)。
  - 间距与尺寸衰减：间距 `20px`，各级比例依次为 `1.0 -> 0.88 -> 0.76`。
  - 行波脉冲：\(\text{pulse} = 0.30 + 0.70 \times \sin(\text{phase} \times \pi)\)，沿主轴顺畅行进。

---

## 四、工程架构与流水线集成协议（Codex 规范）

### 1. 配置层：`src/config/settings.py`
遵守单真相源铁律（严禁在业务代码中调用 `os.getenv`）：
```python
# Interaction Overlay (Project Runway-CTA)
enable_interaction_overlay: bool = False  # 生产安全默认 False
interaction_trigger_early_ratio: float = 0.18  # 黄金认知点比例
interaction_trigger_end_seconds: float = 14.0  # 片尾倒数秒数
interaction_sound_enabled: bool = True
interaction_sound_volume: float = 0.40
```

### 2. 跨平台字体解析策略
严禁在生产代码中硬编码单一平台字体路径，必须实现自动回退机制：
```python
def resolve_render_font(size: int, bold: bool = True):
    candidates = [
        settings.default_font_path,
        PROJECT_ROOT / "assets" / "fonts" / "SourceHanSerifCN-Medium.otf",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    ...
```

### 3. 切片编号与资产命名规则
- 必须完整沿用 `pipeline_manager.py` 既有的切片前缀命名协议：
  ```python
  prefix = f"{yid}_s{slice_index}" if slice_index > 0 else yid
  ```
- **基础成片（字幕压制后）**：`{prefix}_vertical.mp4`
- **互动成片（叠加动效后）**：`{prefix}_vertical_interactive.mp4`

### 4. 发布选片与优雅降级协议
流水线各发布分支（微信视频号 `wechat_uploader`、抖音 `_douyin_asset_paths`、快手 `_kuaishou_asset_paths` 及 Telegram 审核副本）统一通过中央选片方法获取最终成片路径：
```python
def _get_published_video_path(self, prefix: str) -> Path:
    """返回最终发布的视频文件：开启互动层且成片有效时使用 interactive，否则平滑降级为 vertical。"""
    if settings.enable_interaction_overlay:
        interactive = self._OUT_DIR / f"{prefix}_vertical_interactive.mp4"
        if interactive.is_file():
            is_valid, _ = _validate_rendered_vertical_cache(interactive, ...)
            if is_valid:
                return interactive
    return self._OUT_DIR / f"{prefix}_vertical.mp4"
```

### 5. 缓存失效与防重复渲染规则（Cache Invalidation）
1. **上游成片更新即失效**：如果 `{prefix}_vertical.mp4` 的修改时间（mtime）大于 `{prefix}_vertical_interactive.mp4`，说明字幕、标题或源剪辑已发生变动，既有互动缓存立刻失效，强制重新执行合成。
2. **开关关闭即回退**：若 `settings.enable_interaction_overlay=False`，流水线完全不生成且忽略 `_interactive.mp4`，平滑回退至既有 `{prefix}_vertical.mp4`。
3. **假成片与完整性校验**：必须通过 `get_video_duration_ffprobe` 验证 `{prefix}_vertical_interactive.mp4` 可解析，且时长在基础视频 `±0.5s` 误差内、大小 `>1MB`，杜绝 FFmpeg 截断损坏文件流入发布。

---

## 五、验收标准与开发节奏（已完成）
1. **实现产出**：
   - 核心处理器：`src/video_processing/processors/interaction_overlay.py` (`InteractionOverlayProcessor`)
   - 配置项扩展：`src/config/settings.py` (`enable_interaction_overlay=False` 安全默认)
   - 流水线调度挂载：`src/video_processing/pipeline_manager.py`（发布中央选片 `_get_published_video_path`、mtime失效、切片编号继承）
2. **单元测试与沙箱验收通过**：
   - 测试文件：`tests/unit/test_interaction_overlay.py`（覆盖字体回退、wave音效合成、45°跑道微标、100%字幕洁净度、错峰时延、触发计算与缓存失效）
   - 沙箱测试执行：
     ```bash
     .venv/bin/python scripts/run_isolated_tests.py -- -q tests/unit/test_interaction_overlay.py
     # 结果: pytest: {"exit_code": 0, "seconds": 1.402}，测试全部通过
     ```
3. **线上生产安全性保障**：
   - 特性开关默认关闭 (`enable_interaction_overlay=False`)，主流水线透明降级至 `{prefix}_vertical.mp4`，对既有生产零破坏、零风险。
