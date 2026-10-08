# 二创编辑模板

2026-10-08，Codex。视觉规格见 `docs/specs/masterpiece-visual-quality.md`。

V2 生产路径使用暖白、墨黑、铜色的编辑版式。原片按比例完整放入独立画面区，
复用双语 ASS 的台词和时码，移除旧版定位样式；两组洞察各三点依次显示。
片头使用真实原片摄影，分句口播与字幕按实际合成音长同步。
片尾显示问题、纯文字选项和真实微信视频号码，同时显示并朗读：

> 欢迎在评论区说说你的判断。

此句由 `OutroSegment.comment_invitation` 提供，画面、口播、发布前文案审查共用，
不用生成模型重复添加。修改模板文案或版式时需要更新 `RENDER_RECIPE` 使历史缓存失效。

## 入口与资产

共享流水线与独立 `scripts/run_masterpiece.py` 均调用 `InsightProcessor`。
给定 `output/<prefix>_vertical.mp4`，在同目录及 `original_video/` 查找同 prefix
原片（mp4/mkv/webm/mov）和 `.ass`。切片必须有自己的原片及字幕，不借用父视频。
缺少素材、字幕无法无损识别或原片时长不符时返回增强失败，共享流水线保留普通成片。

自定义文件名通过 `--original-video <path>`、`--bilingual-subtitle <path>` 指定，
它们与 `--source-video`（基础成片）、`--subtitle`（事实核查源字幕）用途不同。
独立入口示例：

```sh
.venv/bin/python scripts/run_masterpiece.py U7TXk5wXa_w \
  --source-video output/U7TXk5wXa_w_vertical.mp4 \
  --original-video output/original_video/U7TXk5wXa_w.mp4 \
  --bilingual-subtitle output/original_video/U7TXk5wXa_w.ass \
  --script output/U7TXk5wXa_w_insight.json
```

收据增加原片、双语字幕指纹及六条洞察的实际时窗；字体、声音供应商/音色/语速、
品牌资产、转场音量仍纳入缓存。主体没有 trim/atrim、空间裁切或覆面横栏。
字幕使用项目已有 imageio-ffmpeg/libass 运行时，不增加网页渲染框架。

普通事实疑点继续留档提示，不停止发布；既有内容安全审查仍然适用。
本入口生成母带与渲染状态，不代表平台上传或公开发布。
微信视频号码不是普通 QR；完整图案等比缩放及静区可由程序检查，微信扫码需设备端验收。

本次实现与真实样片证据见 `docs/verification/masterpiece-editorial-2026-10-08.md`。
