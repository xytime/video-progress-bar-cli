---
created_by: Claude_Sonnet_4.6_Thinking_planning
created_at: 2026-05-21T17:58:00+08:00
---

# Version History

| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-05-21 | Claude_Sonnet_4.6_Thinking_planning | 初始创建端口注册中心 |
| 1.1.0 | 2026-06-18 | Claude_Opus_4.8 | Video-precessing 仪表盘端口 8765 → 9100；本项目专属区间改为 `9100–9199`，避开 :8080（其他项目股票服务） |

# 端口注册中心 (Port Registry)

> **规范**：新服务上线前，必须先在此文档登记端口，避免跨项目冲突。
> 端口范围：**Video-precessing 专属区间为 `9100–9199`**（旧建议 7700–7999 已废弃）。禁止占用常用框架端口及 `8080`（其他项目股票服务）。

## 已注册端口

| 端口 | 项目 | 服务名称 | 启动命令 |
| --- | --- | --- | --- |
| `8000` | **OptionSense** | Web UI 控制台 | `ui start` (OptionSense) |
| `9100` | **Video-precessing** | Pipeline 仪表盘 | `./vpanel ui start`（`settings.dashboard_port`，可经 `DASHBOARD_PORT` 覆盖） |

## 保留/禁用端口（勿占）

| 端口 | 原因 |
| --- | --- |
| `3000` | React / Next.js dev server 默认 |
| `4200` | Angular CLI 默认 |
| `5000` | Flask 默认 |
| `5173` | Vite dev server 默认 |
| `8080` | **其他项目（股票服务 uvicorn）占用** / HTTP 代理 / Spring Boot 默认 — 视频处理严禁占用 |
| `8888` | Jupyter Notebook 默认 |
| `8501` | Streamlit 默认 |
| `7860` | Gradio 默认 |

## 新服务注册流程

1. 查阅上表，确认目标端口未被占用
2. 在本表"已注册端口"中填入 `端口 | 项目 | 服务名称 | 启动命令`
3. 在代码中通过**环境变量**（而非硬编码）声明端口，例如 `DASHBOARD_PORT=9100`
4. Commit 时同步更新本文档
