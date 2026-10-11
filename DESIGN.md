---
version: alpha
colors:
  background: "#07071a"
  surface: "#0d0d24"
  primary: "#a78bfa"
  focus: "#2dd4bf"
  text: "#e2e8f0"
  secondary: "#94a3b8"
typography:
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, PingFang SC, sans-serif"
    fontSize: "16px"
    lineHeight: "1.65"
rounded:
  panel: "14px"
  control: "8px"
omitted:
  - section: spacing
    reason: "Existing dashboard spacing is contextual rather than a shared scale."
  - section: components
    reason: "Vanilla HTML and CSS are the maintained runtime owners; see Components below."
---

## Overview
Video Pipeline 中文运营控制台。产品表单优先任务清晰与状态可核实，沿用深蓝背景、紫色操作和青色重点。商品页的核心是五类视频与书籍映射，不新增营销式大数字或装饰性卡片。

## Colors
运行源为 `src/web/static/css/dashboard.css` 的 `:root`，本文记录现有值，不生成独立主题。
background → `--bg`，surface → `--bg2`，primary → `--accent2`，focus → `--teal`，text → `--text`，secondary → `--text2`。
错误同时提供文本说明与 `--red`；状态不依赖颜色。此次商品页采用默认深色，不改既有控制台外观偏好。

## Typography
正文与表单使用系统中文回退；标题 28px、分区 19px。全称与商品 ID 换行显示，选项短名之外保留完整身份文本。

## Layout
商品页单列自然滚动，最大 1040px；桌面首选与备选并排，600px 以下单列。保存状态置顶，表单后提供预览。保存不导航，便于连续核对配置与结果。

## Elevation & Depth
复用透明浅色面板与轻边框。不增加动画；页面在 reduced motion 下行为相同。

## Shapes
面板复用 `--radius`，控件复用 `--radius-sm`。商品页面专属布局由 `product_settings.css` 持有。

## Components
| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | 原生 HTML select | 既有控制台原生 select；本页接受操作系统弹层 | native | 中文选项、键盘与窄屏浏览器测试 |
| Form | product_settings.html / product_settings.js | web/product_settings.py 最终校验 | 独立配置编辑 | 保存、验证失败、保留草稿测试 |
| Scrollbar | dashboard.css | :root 滚动条变量 | 全局继承，几何例外按旧控制台 | computed style、窄屏 |
| Toast | 商品页持久 role=status | 配置与采用是不同状态 | 持久配置反馈 | 保存不伪造采用测试 |
| CRUD | web/product_settings.py | 已确认选品规格 | 保存留在本页，无删除或外部发布 | 实际 API 浏览器往返 |

没有现成共享 schema 表单库。复用原生 select、既有 dashboard.css 变量与控制台导航样式。
草稿丢失提示由原生 dialog 与页面脚本持有，焦点默认继续编辑；仅卸载使用 beforeunload。
静态审计工具仅识别内联 onclick；本页使用独立脚本绑定真实事件，不为静态工具加入空处理器。对应告警由浏览器交互验证解释。

## Do's and Don'ts
按 `docs/specs/wechat-product-link-2026-10-10.md` 的已确认业务规则显示五组、默认回退与采用状态。
不将预览写成平台可用，不将保存写成实际采用。无当前平台 DOM 证据时不写挂载成功。
