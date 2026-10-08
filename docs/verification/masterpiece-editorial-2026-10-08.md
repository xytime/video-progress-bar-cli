# 二创编辑模板验收记录

作者：Codex；日期：2026-10-08。用户已确认视觉方案及评论区邀请。

## 实现范围

- 独立入口和共享增强路径统一使用 `InsightProcessor` 的 V2 编辑模板。
- 原片按比例完整展示，双语字幕和六条洞察在独立区域依时序显示。
- 暖白、墨黑、铜色版式；片头真实摄影、句级配音字幕；片尾问题、选项与真实品牌码。
- “欢迎在评论区说说你的判断。”由同一属性供画面、口播与文案审查使用。
- 原片、ASS、字体、声音配置和品牌资产进入缓存校验；缺失必要素材回退基础成片。
- 延续此前修复：事实疑点留档提示，不因普通疑点停止发布；V2 生产路径拒绝 V1 降级和正文裁切。

## 本地证据

样片目录：`/Users/ryusei/.codex/worktrees/153c/Video-precessing/output/editorial-acceptance/`。
大媒体及详细测试日志保存在该本地目录，不进入 Git。

| 检查 | 结果 |
| --- | --- |
| 相关隔离测试 | 63 passed；8 条已有 websocket 弃用告警 |
| 架构扫描器回归 | 78 passed；所改维护模块扫描无强制违规 |
| 真实渲染 | 真实 Doubao 配音、Wall Street 原片与现有双语 ASS |
| 成片 | `wallstreet-editorial.mp4`，1080×1920，30 fps，690.100 秒 |
| 音频 | 双声道 44100 Hz，690.097007 秒；尾差 2.993 毫秒 |
| 正文保留 | 原片 666.853878 秒；正文段按帧补齐至 666.866667 秒，无时间或空间裁切 |
| 全片解码 | FFmpeg 全片解码退出 0，无错误输出 |
| 缓存 | 同一输入与真实配置连续两次 `valid_enrichment=True` |
| 视觉 | 19 张实际成片抽帧，含旧问题位置 134/151/281 秒、六条洞察中点、四组起止边界 |
| 可读性 | 390 px 宽抽帧检查通过；百分数不拆分、行首无孤立逗号，无新增覆面文字 |
| 评论邀请音轨 | 本地 Whisper small 从片尾实际音轨独立识别出“歡迎在評論區說說你的判斷” |

成片 SHA-256：
`a1e066df5366df1a3cb6e05c0611b7831b1000d908bd700d512a49db97f97ed4`。

目录中的证据：`wallstreet-editorial.receipt.json`、`qa.json`、`preview-390.png`、
`all-six-points.png`、`boundaries.png`、`frames/`、`outro-asr.json`、
`render-tests-receipt.json`、`render-tests.log`、`scanner-tests-receipt.json`、`scanner-tests.log`。

相关测试命令（通过项目隔离运行器执行）：

```sh
.venv/bin/python scripts/run_isolated_tests.py -- -q \
  tests/unit/test_insight_script_v2.py tests/unit/test_insight_processor.py \
  tests/unit/test_insight_processor_v2.py tests/unit/test_insight_advisory.py \
  tests/unit/test_doubao_tts.py tests/unit/test_insight_editorial.py
```

## 证据边界

上述结果确认本地代码、真实完整样片及缓存复用，不代表整条发现到发布流程完成。
样片直接调用处理器，没有更新生产视频记录、上传、重发历史作品或发送评论。
微信视频号码已检查完整图案与静区；设备端微信扫码尚未验证。
ASR 只核对评论邀请确实进入音轨，不替代人工听感评审或事实正确性判断。
