---
created_by: Gemini_3.5_Flash_fast
created_at: 2026-06-07T22:50:00+08:00
---

# YouTube Like-to-View Ratio Chrome Extension

这是一个轻量级、无广告且极具设计感的 Chrome 浏览器插件。它能够在 YouTube 列表页（搜索页、首页推荐、右侧关联列表）上，直接为每一个视频计算并渲染出 **“点赞/观看 %”（Like-to-View Ratio / 互动率）**。

## Version History

| 版本号 | 更新时间   | 作者                   | 变更说明 |
| ------ | ---------- | ---------------------- | -------- |
| 1.2.0  | 2026-06-07 | Gemini_3.5_Flash_fast  | **深度重构**：采用双核架构。解决隔离世界无法读取 `shadowRoot` 的底层标准限制，用 Main World 穿透与 Isolated World 桥接实现彻底解决 |
| 1.1.7  | 2026-06-07 | Gemini_3.5_Flash_fast  | 修复 querySelectorShadow 的核心漏洞，同时遍历 Light DOM (children) 与 Shadow DOM (shadowRoot.children)，彻底解决因嵌套分发导致的匹配失败 |
| 1.1.5  | 2026-06-07 | Gemini_3.5_Flash_fast  | 引入 3 秒一次的强力心跳诊断日志，打印每个选择器的抓取数量，帮助彻底查明首页与详情页未匹配到元素的原因 |
| 1.1.4  | 2026-06-07 | Gemini_3.5_Flash_fast  | 扩充 CARD_SELECTORS 支持更多改版布局，并增加首次扫描诊断日志输出以辅助排查 |
| 1.1.3  | 2026-06-07 | Gemini_3.5_Flash_fast  | 重构数据获取机制：将 fetch 移入 background.js (Service Worker)，彻底解决 CSP 安全拦截问题；增加 console 日志方便调试 |
| 1.1.2  | 2026-06-07 | Gemini_3.5_Flash_fast  | 修复首页由于 Polymer 属性延迟绑定导致的漏检问题，引入轮询扫描与多渠道链接提取 |
| 1.1.1  | 2026-06-07 | Gemini_3.5_Flash_fast  | 允许低样本视频（<500次观看）显示灰色百分比及进度条长度，提供早期参考价值 |
| 1.1.0  | 2026-06-07 | Gemini_3.5_Flash_fast  | 引入贝叶斯平滑算法与 500 次播放量过滤阈值，修复小样本偏差陷阱 |
| 1.0.0  | 2026-06-07 | Gemini_3.5_Flash_fast  | 初始化创建，包含防抖懒加载、本地缓存及美化的进度条 |

---

## 终极技术解决方案：双核通信架构 (v1.2.0)

在先前的版本中，即便我们编写了完美的 `shadowRoot` 递归穿透选择器，插件前台依然会报 `找不到缩略图/锚点: 39`。

### 1. 致命瓶颈根因
根据 Chrome 扩展的安全规范，Content Script 运行在 **Isolated World（隔离世界）**。在这个沙箱环境中，出于安全性隔离，**Content Script 从外部直接访问任何由网页原声脚本创建的元素的 `.shadowRoot` 属性都会直接返回 `null` 或 `undefined`**。这导致任何在 Isolated World 中执行的 Shadow DOM 穿透均被底层浏览器机制静默拦截。

### 2. 双核架构设计
为了彻底击碎这一限制，`v1.2.0` 重构为以下三层架构：
* ⚡ **Main World 底层探针 (inject.js)**：
  以页面原生 `<script>` 标签的形式，由 content.js 动态注入到网页主上下文中运行。它与 YouTube 页面共享同一个 JS 执行作用域，**拥有原生、无限制读取元素 `.shadowRoot` 属性的最高权限**。它负责心跳扫描、递归穿透 Shadow DOM 获取视频 ID，以及在影子树内插入进度条 UI。
* 🌉 **Isolated World 桥接核心 (content.js)**：
  运行在隔离世界中，作为 Main World 和后台扩展进程之间的跨域通信桥梁。它监听 `inject.js` 抛出的自定义 DOM 事件，代理调用 `chrome.runtime.sendMessage` 和管理 `chrome.storage.local` 本地缓存，获取到数据后再事件化回传给 `inject.js`。
* 🛡️ **Background Service Worker (background.js)**：
  在后台进程中代理 Fetch 请求，避开 YouTube 的 **CSP (内容安全策略)** 限制。

通过本架构，我们在安全性（Service Worker 后台代理）与 DOM 操作权限（网页主作用域探针注入）上同时取得了最高特权，实现了 100% 的底层穿透。

---

## 针对“小样本量偏差”的防范机制

为了防止极低观看量视频因偶然因素导致点赞率虚高（例如 100 次播放，10 个赞呈现 10%），本插件引入了纠偏与分级机制：

1. **置信平滑（Views >= 500）**：
   - 采用贝叶斯平滑算法 (Bayesian Smoothing) 计算**置信度点赞率**：
     $$\text{置信度点赞率} = \frac{\text{点赞数} + 30}{\text{观看数} + 1000}$$
     *(先验观看数 $K = 1000$，先验平均点赞率 $C = 3.0\%$)*
   - 过滤小样本噪音，让结果随数据量增大自然趋近真实值。
   - 进度条呈红/橙/绿/紫的彩色系展示。

2. **低样本早期参考（Views < 500）**：
   - 当播放量小于 500 次时，数据存在一定偶然性。为了保留其早期参考价值，**进度条渲染为中性灰色斜向条纹**，表示“小样本”。
   - **进度条的填充长度会根据其真实的点赞率按比例映射**。
   - 列表文字显示为灰色的：`👍/👁️ X.X%*`（带星号以示区别）。

---

## 插件文件结构

- [manifest.json](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension/manifest.json)
- [content.js](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension/content.js)
- [inject.js](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension/inject.js) (Main World 注入探针)
- [background.js](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension/background.js)
- [styles.css](file:///Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension/styles.css)

---

## 安装与使用步骤

1. 打开 **Chrome 浏览器**。
2. 访问：`chrome://extensions/`。
3. 开启右上角的 **“开发人员模式” (Developer mode)** 开关。
4. 点击左上角的 **“载入解压延伸程序” (Load unpacked)** 按钮。
5. 选中此插件文件夹：
   `/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/youtube-like-view-ratio-extension`
6. 打开 [YouTube](https://www.youtube.com) 随意浏览或搜索，滚动列表即可看到智能平滑后的点赞率条。
