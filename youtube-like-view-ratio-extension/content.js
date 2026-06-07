/**
 * Modification History
 * 
 * Version | Date       | Author               | Description
 * --------|------------|----------------------|----------------------------------------------------
 * 1.2.0   | 2026-06-07 | Gemini_3.5_Flash_fast| 重构为双核通信架构，content.js 仅作为 Isolated World 通信桥梁，负责动态注入 inject.js 到 Main World 并代理 background 请求与本地存储
 * 1.1.7   | 2026-06-07 | Gemini_3.5_Flash_fast| 修复 querySelectorShadow 的核心漏洞，同时遍历 Light DOM (children) 与 Shadow DOM (shadowRoot.children)，彻底解决因嵌套分发导致的匹配失败
 * 1.1.5   | 2026-06-07 | Gemini_3.5_Flash_fast| 引入 3 秒一次的强力心跳诊断日志，打印每个选择器的抓取数量，帮助彻底查明首页与详情页未匹配到元素的原因
 * 1.1.4   | 2026-06-07 | Gemini_3.5_Flash_fast| 扩充 CARD_SELECTORS 兼容更多 YouTube 改版布局；在 scanAndProcess 中增加首次扫描诊断报告，帮助准确定位首页不显示的原因
 * 1.1.3   | 2026-06-07 | Gemini_3.5_Flash_fast| 将直接 fetch 替换为向 background service worker 发送消息请求数据，绕过 CSP 跨域拦截；增加控制台打点调试日志
 * 1.1.2   | 2026-06-07 | Gemini_3.5_Flash_fast| 将 MutationObserver 替换为 setInterval 轮询，支持多渠道链接提取，修复首页由于 Polymer 属性延迟绑定导致的漏检问题
 * 1.1.1   | 2026-06-07 | Gemini_3.5_Flash_fast| 支持对 500 次播放量以下的视频显示灰色真实点赞百分比和对应的灰色进度条长度
 * 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_fast| 引入贝叶斯平滑(Bayesian Smoothing)与样本量过滤，解决小样本偏差陷阱
 * 1.0.0   | 2026-06-07 | Gemini_3.5_Flash_fast| 初始化创建，包含防抖懒加载、本地缓存及美化的进度条
 */

(function () {
  'use strict';

  // [Gemini_3.5_Flash_fast] 缓存有效期：24小时
  const CACHE_EXPIRY = 24 * 60 * 60 * 1000;
  
  // [Gemini_3.5_Flash_fast] 贝叶斯平滑先验参数
  const PRIOR_VIEWS = 1000;
  const PRIOR_LIKES = PRIOR_VIEWS * 0.03; // 30 个点赞

  console.log('[Like-to-View] 桥接插件(Content Script)已加载，开始初始化 Main World 探针...');

  // 1. 动态注入 inject.js 到网页主作用域 (Main World)
  try {
    const script = document.createElement('script');
    script.src = chrome.runtime.getURL('inject.js');
    script.onload = function() {
      this.remove(); // 注入完成后即刻移出 DOM 保持整洁
    };
    (document.head || document.documentElement).appendChild(script);
  } catch (err) {
    console.error('[Like-to-View] 注入探针失败:', err);
  }

  // 2. 接收来自 Main World 的数据请求
  window.addEventListener('YT_NEED_RATIO', async (event) => {
    const { videoId } = event.detail;
    if (!videoId) return;

    let likes = null;
    let views = null;

    try {
      // 2.1. 尝试从本地缓存读取
      const cached = await chrome.storage.local.get(videoId);
      if (cached[videoId] && (Date.now() - cached[videoId].timestamp < CACHE_EXPIRY)) {
        likes = cached[videoId].likes;
        views = cached[videoId].views;
      } else {
        // 2.2. 通过 Service Worker 后台代理获取数据，规避 CSP 限制
        const response = await chrome.runtime.sendMessage({
          action: 'getStats',
          videoId
        });

        if (response && response.success && response.data) {
          const data = response.data;
          likes = data.likes;
          views = data.viewCount;

          // 写入本地缓存
          await chrome.storage.local.set({
            [videoId]: { likes, views, timestamp: Date.now() }
          });
        }
      }

      if (likes !== null && views >= 0) {
        const rawRatio = views > 0 ? (likes / views) * 100 : 0;
        const smoothedRatio = ((likes + PRIOR_LIKES) / (views + PRIOR_VIEWS)) * 100;

        // 回传数据事件给 Main World
        sendDataToMainWorld(videoId, true, rawRatio, smoothedRatio, likes, views);
      } else {
        sendDataToMainWorld(videoId, false);
      }

    } catch (err) {
      console.warn(`[Like-to-View] 处理视频数据出错: ${videoId}`, err);
      sendDataToMainWorld(videoId, false);
    }
  });

  // [Gemini_3.5_Flash_fast] 向主页面发送事件回传数据
  function sendDataToMainWorld(videoId, success, rawRatio = 0, smoothedRatio = 0, likes = 0, views = 0) {
    window.dispatchEvent(new CustomEvent('YT_RECEIVE_RATIO', {
      detail: {
        videoId,
        success,
        rawRatio,
        smoothedRatio,
        likes,
        views
      }
    }));
  }

})();
