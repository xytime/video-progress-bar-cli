---
version: 1
name: Video Console
description: 商品管理工作台，优先显示五类配置与真实执行状态
omitted:
  - section: colors
    reason: dashboard.css 的语义主题变量为唯一运行时颜色来源
  - section: typography
    reason: 继承 dashboard 字号偏好；product_settings.css 定义业务角色比例
  - section: rounded
    reason: product_settings.css 定义 6px 控件与 8px 面板
  - section: spacing
    reason: product_settings.css 定义工作台网格与响应式间距
  - section: components
    reason: UX-CONTRACT.md 记录当前业务组件所有者与验证
---

# 视频控制台设计约定

2026-10-11 用户批准商品挂载静态效果图。此约定覆盖商品管理，其他既有页面按需迁移。

产品定位：中文运营管理工具。日常任务是为五类视频指定首选、备选与全局默认，查看影响后保存。避免巨型介绍卡片、渐变装饰和长表单堆叠。

默认页面让五类配置在桌面首屏可见；商品库和执行记录为并列入口。商品资料、导入和历史在对话框中处理；顶部保留保存入口和修改数量。手机将每类配置转为独立两列卡片，保留标签，不横向溢出。

主题变量由 `src/web/static/css/dashboard.css` 唯一提供，沿用控制台暗、亮、高对比与字号偏好。商品页主操作引用 `--blue`；`--bg`、`--glass`、`--border`、`--text`、`--text2` 分别承担背景、面板、分隔与文字层级。不改动控制台其他业务主题。布局所有者为 `src/web/static/css/product_settings.css`。

字号使用系统中文字体：页面标题 1.5rem，段标题 1rem，主要内容 .875rem，操作/辅助信息 .75rem。正文不强行全大写；精确 ID 与完整名称可在商品详情和编辑页核对。省略展示不修改原始商品名称。

控件圆角 6px，面板 8px；主要间距 12/14/18px。页面最大宽度1480px；1050px以下详情区转下方，600px以下为手机布局。页面自然滚动，不锁定共享页面高度；对话框内部滚动并保留底部操作。

商品搜索弹层由 `product_picker.js` 统一维护：显示框为应用按钮，选择列表为原生 `<select size>`，保留系统键盘及辅助技术语义，不手写 ARIA listbox。为长中文名称，桌面弹层宽度至少380px，窄屏限制为可用视口宽度；这是明确的宽度例外。库中全部候选均可检索，停用候选不能提交。详情显示原始完整名称，不把历史库存当实时可售。

静态效果图参考位于 `/Users/ryusei/.codex/generated_images/01a1248b-c700-7bd2-8122-ea52f9859b50/exec-2cc9f294-dbdd-4842-9903-a317786a8011.png`。示例搭配不能写入运营配置。
