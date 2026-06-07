/**
 * Modification History
 * 
 * Version | Date       | Author               | Description
 * --------|------------|----------------------|----------------------------------------------------
 * 1.2.3   | 2026-06-07 | Gemini_3.5_Flash_planning | 兼容 YouTube 新版首页卡片布局 yt-lockup-view-model，支持 Light DOM 渲染与 text 渲染 fallback 链路
 * 1.2.2   | 2026-06-07 | Gemini_3.5_Flash_planning | 解决 YouTube 严格 Trusted HTML (Trusted Types) 策略下直接写入 innerHTML 被阻止的 bug，改用标准 DOM API 渲染
 * 1.2.1   | 2026-06-07 | Gemini_3.5_Flash_planning | 针对红蓝审计结果进行加固：解决 SPA 视频卡片复用渲染脏数据、引入 10 秒超时清理防范内存泄露，并支持原地更新
 * 1.1.0   | 2026-06-07 | Gemini_3.5_Flash_planning | 深度修复 Shadow DOM 穿透和样式隔离，支持影子 DOM 内部渲染和动态 CSS 注入
 * 1.0.0   | 2026-06-07 | Gemini_3.5_Flash_fast| 初始创建 inject.js，作为 Main World 注入脚本运行，100% 穿透 Polymer 的 Shadow DOM
 */

(function () {
  'use strict';

  const MAX_RATIO_THRESHOLD = 8.0;
  const MIN_VIEWS_THRESHOLD = 500;

  // # [Gemini_3.5_Flash_planning] 扩充 CARD_SELECTORS 支持新版 yt-lockup-view-model 卡片标签
  const CARD_SELECTORS = [
    'ytd-video-renderer',
    'ytd-rich-item-renderer',
    'ytd-rich-grid-media',
    'ytd-rich-grid-video-renderer',
    'ytd-compact-video-renderer',
    'ytd-grid-video-renderer',
    'ytd-playlist-video-renderer',
    'ytd-rich-grid-slim-media',
    'yt-lockup-view-model'
  ];

  // # [Gemini_3.5_Flash_planning] 样式中添加对新布局缩略图容器 a.ytLockupViewModelContentImage 的支持，设置相对定位及悬停行为
  const STYLE_ID = 'yt-like-view-ratio-styles';
  const CSS_TEXT = `
    a#thumbnail,
    a.ytLockupViewModelContentImage {
      position: relative !important;
      display: block !important;
    }
    .yt-like-view-ratio-bar-container {
      position: absolute;
      bottom: 0;
      left: 0;
      width: 100%;
      height: 4px;
      background-color: rgba(15, 15, 15, 0.7);
      backdrop-filter: blur(2px);
      z-index: 15;
      overflow: hidden;
      transition: height 0.15s ease-in-out;
      cursor: help;
    }
    a#thumbnail:hover .yt-like-view-ratio-bar-container,
    a.ytLockupViewModelContentImage:hover .yt-like-view-ratio-bar-container,
    .yt-like-view-ratio-bar-container:hover {
      height: 6px;
    }
    .yt-like-view-ratio-bar-fill {
      height: 100%;
      border-radius: 0 2px 2px 0;
      transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
    }
    .yt-like-view-ratio-bar-fill.ratio-insufficient {
      background: repeating-linear-gradient(
        45deg,
        #7f8c8d,
        #7f8c8d 6px,
        #95a5a6 6px,
        #95a5a6 12px
      );
      opacity: 0.6;
    }
    .yt-like-view-ratio-bar-fill.ratio-low {
      background: linear-gradient(90deg, #ff4b5c, #ff6b81);
    }
    .yt-like-view-ratio-bar-fill.ratio-medium {
      background: linear-gradient(90deg, #ffa502, #ff7f50);
    }
    .yt-like-view-ratio-bar-fill.ratio-high {
      background: linear-gradient(90deg, #2ed573, #1dd1a1);
    }
    .yt-like-view-ratio-bar-fill.ratio-super {
      background: linear-gradient(90deg, #00d2d3, #a55eea);
      box-shadow: 0 0 4px rgba(165, 94, 234, 0.8);
    }
  `;

  // [Gemini_3.5_Flash_fast] 临时存放正在等待查询结果的卡片 DOM 节点，videoId -> Set(cardElements)
  const pendingCards = new Map();

  function formatNumber(num) {
    if (!num) return '0';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'k';
    return num.toString();
  }

  function extractVideoId(urlStr) {
    if (!urlStr) return null;
    try {
      const url = new URL(urlStr, window.location.origin);
      if (url.pathname.startsWith('/watch')) return url.searchParams.get('v');
      if (url.pathname.startsWith('/shorts/')) {
        const parts = url.pathname.split('/');
        return parts[2] || null;
      }
    } catch (e) {
      const matchWatch = urlStr.match(/\/watch\?v=([^&#]+)/);
      if (matchWatch) return matchWatch[1];
      const matchShorts = urlStr.match(/\/shorts\/([^/?#]+)/);
      if (matchShorts) return matchShorts[1];
    }
    return null;
  }

  /**
   * 递归穿透 Shadow DOM 并兼顾 Light DOM 分发子节点的深度元素查找
   * # [Gemini_3.5_Flash_fast] 运行在 Main World 下能够真正获取到 open 状态的 shadowRoot 并穿透
   */
  function querySelectorShadow(root, selector) {
    if (!root) return null;
    if (root.querySelector) {
      const el = root.querySelector(selector);
      if (el) return el;
    }
    if (root.shadowRoot) {
      const el = querySelectorShadow(root.shadowRoot, selector);
      if (el) return el;
    }
    if (root.children) {
      for (let i = 0; i < root.children.length; i++) {
        const el = querySelectorShadow(root.children[i], selector);
        if (el) return el;
      }
    }
    if (root.shadowRoot && root.shadowRoot.children) {
      const shadowChildren = root.shadowRoot.children;
      for (let i = 0; i < shadowChildren.length; i++) {
        const el = querySelectorShadow(shadowChildren[i], selector);
        if (el) return el;
      }
    }
    return null;
  }

  /**
   * 递归穿透所有影子 DOM 查找卡片元素，并以最外层匹配卡片为准终止递归（优化性能）
   * # [Gemini_3.5_Flash_planning]
   */
  function findCardsShadow(root, selectors, results = []) {
    if (!root) return results;

    if (root.tagName) {
      const tagNameLower = root.tagName.toLowerCase();
      if (selectors.includes(tagNameLower)) {
        results.push(root);
        return results; // 终止当前分支递归，不在卡片内嵌套查找
      }
    }

    // 递归子节点
    if (root.children) {
      for (let i = 0; i < root.children.length; i++) {
        findCardsShadow(root.children[i], selectors, results);
      }
    }

    // 递归 shadowRoot 子节点
    if (root.shadowRoot && root.shadowRoot.children) {
      const shadowChildren = root.shadowRoot.children;
      for (let i = 0; i < shadowChildren.length; i++) {
        findCardsShadow(shadowChildren[i], selectors, results);
      }
    }

    return results;
  }

  /**
   * 动态向影子 DOM 内部注入进度条所需的 CSS 样式
   * # [Gemini_3.5_Flash_planning]
   */
  function injectStylesIntoShadow(shadowRoot) {
    if (!shadowRoot) return;
    if (!shadowRoot.getElementById(STYLE_ID)) {
      const style = document.createElement('style');
      style.id = STYLE_ID;
      style.textContent = CSS_TEXT;
      shadowRoot.appendChild(style);
    }
  }

  // # [Gemini_3.5_Flash_planning] 支持新版布局 a.ytLockupViewModelContentImage 和 title 链接的 ID 提取
  function findVideoIdInCard(card) {
    const thumbnailAnchor = querySelectorShadow(card, 'a#thumbnail') || querySelectorShadow(card, 'a.ytLockupViewModelContentImage');
    if (thumbnailAnchor && thumbnailAnchor.href) {
      const id = extractVideoId(thumbnailAnchor.href);
      if (id) return id;
    }

    const titleAnchor = querySelectorShadow(card, 'a#video-title-link') || 
                        querySelectorShadow(card, 'a#video-title') ||
                        querySelectorShadow(card, 'a.ytLockupMetadataViewModelTitle');
    if (titleAnchor && titleAnchor.href) {
      const id = extractVideoId(titleAnchor.href);
      if (id) return id;
    }

    return null;
  }

  // 观察卡片是否可见
  const intersectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const card = entry.target;
        const videoId = card.dataset.ytVideoId;
        
        intersectionObserver.unobserve(card);
        
        if (videoId) {
          // 发起广播通知 Content Script 去获取数据
          requestRatioData(card, videoId);
        }
      }
    });
  }, {
    rootMargin: '200px 0px'
  });

  function requestRatioData(card, videoId) {
    // 放入待处理队列
    if (!pendingCards.has(videoId)) {
      pendingCards.set(videoId, new Set());
      
      // # [Gemini_3.5_Flash_planning] 漏洞防护：10秒超时自动清理，防止因 API 失败或路由卸载导致 Set 累积引起内存泄露
      setTimeout(() => {
        if (pendingCards.has(videoId)) {
          pendingCards.delete(videoId);
        }
      }, 10000);
    }
    pendingCards.get(videoId).add(card);

    // 触发自定义事件，抛给前台 Content Script
    window.dispatchEvent(new CustomEvent('YT_NEED_RATIO', {
      detail: { videoId }
    }));
  }

  // 监听 Content Script 传回的数据
  window.addEventListener('YT_RECEIVE_RATIO', (event) => {
    const { videoId, rawRatio, smoothedRatio, likes, views, success } = event.detail;
    if (!success) {
      pendingCards.delete(videoId);
      return;
    }

    const cards = pendingCards.get(videoId);
    if (cards) {
      cards.forEach(card => {
        renderUI(card, rawRatio, smoothedRatio, likes, views);
      });
      pendingCards.delete(videoId);
    }
  });

  // # [Gemini_3.5_Flash_planning] 重构后的 renderUI，完美兼容 Shadow DOM (ytd-thumbnail) 和 Light DOM (yt-lockup-view-model) 双重布局
  function renderUI(card, rawRatio, smoothedRatio, likes, views) {
    const thumbnailContainer = querySelectorShadow(card, 'ytd-thumbnail');
    
    // 寻找新旧布局的百分比文本容器
    let metadataLine = querySelectorShadow(card, '#metadata-line');
    if (!metadataLine) {
      // 兼容新版首页 yt-lockup-view-model 的 metadata 结构
      const contentMetadata = querySelectorShadow(card, 'yt-content-metadata-view-model');
      if (contentMetadata) {
        const rows = contentMetadata.querySelectorAll('.ytContentMetadataViewModelMetadataRow');
        if (rows && rows.length > 0) {
          metadataLine = rows[rows.length - 1];
        } else {
          metadataLine = contentMetadata;
        }
      }
    }
    if (!metadataLine) {
      metadataLine = querySelectorShadow(card, '.ytLockupMetadataViewModelMetadata') ||
                     querySelectorShadow(card, '.ytLockupMetadataViewModelTextContainer');
    }

    const isLowSample = views < MIN_VIEWS_THRESHOLD;
    
    let tooltipText = '';
    if (isLowSample) {
      tooltipText = `[新视频/样本少] 真实点赞率: ${rawRatio.toFixed(1)}% (👍 ${formatNumber(likes)} / 👁️ ${formatNumber(views)})\n说明: 播放量较低，数据仅供初期参考。`;
    } else {
      tooltipText = `置信度点赞率: ${smoothedRatio.toFixed(1)}% (真实值: ${rawRatio.toFixed(1)}%)\n数据结构: 👍 ${formatNumber(likes)} / 👁️ ${formatNumber(views)}`;
    }

    // 1. 确保全局文档注入样式（为 Light DOM 的进度条提供样式支持）
    injectStylesIntoShadow(document);

    // 确定当前卡片应挂载进度条的 anchor 和对应的样式作用域
    let anchor = null;
    let styleTargetRoot = null;

    if (thumbnailContainer && thumbnailContainer.shadowRoot) {
      anchor = thumbnailContainer.shadowRoot.querySelector('a#thumbnail');
      styleTargetRoot = thumbnailContainer.shadowRoot;
    } else {
      // 兼容新版首页 Light DOM 缩略图
      anchor = querySelectorShadow(card, 'a.ytLockupViewModelContentImage');
      styleTargetRoot = document;
    }

    if (anchor) {
      if (styleTargetRoot && styleTargetRoot !== document) {
        injectStylesIntoShadow(styleTargetRoot);
      }

      let barContainer = anchor.querySelector('.yt-like-view-ratio-bar-container');
      let barFill = null;

      if (!barContainer) {
        barContainer = document.createElement('div');
        barContainer.className = 'yt-like-view-ratio-bar-container';
        
        barFill = document.createElement('div');
        barFill.className = 'yt-like-view-ratio-bar-fill';
        
        barContainer.appendChild(barFill);
        anchor.appendChild(barContainer);
      } else {
        barFill = barContainer.querySelector('.yt-like-view-ratio-bar-fill');
      }

      barContainer.title = tooltipText;

      const ratio = isLowSample ? rawRatio : smoothedRatio;
      const fillPercentage = Math.min(100, (ratio / MAX_RATIO_THRESHOLD) * 100);
      barFill.style.width = `${fillPercentage}%`;
      
      barFill.className = 'yt-like-view-ratio-bar-fill';
      if (isLowSample) {
        barFill.classList.add('ratio-insufficient');
      } else {
        if (smoothedRatio < 2.0) {
          barFill.classList.add('ratio-low');
        } else if (smoothedRatio < 4.0) {
          barFill.classList.add('ratio-medium');
        } else if (smoothedRatio < 7.0) {
          barFill.classList.add('ratio-high');
        } else {
          barFill.classList.add('ratio-super');
        }
      }
    }

    const ratioFormatted = isLowSample ? `${rawRatio.toFixed(1)}%*` : `${smoothedRatio.toFixed(1)}%`;

    // 2. 渲染/更新比例文字到 metadata 节点
    if (metadataLine) {
      let textSpan = metadataLine.querySelector('.yt-like-view-ratio-text');
      if (!textSpan) {
        textSpan = document.createElement('span');
        textSpan.className = 'yt-like-view-ratio-text';
        metadataLine.appendChild(textSpan);
      }

      textSpan.title = tooltipText;

      // 原地更新内联样式，避免残留旧属性
      textSpan.style.fontSize = '1.2rem';
      textSpan.style.fontWeight = '400';
      textSpan.style.lineHeight = '1.8rem';
      textSpan.style.color = 'var(--yt-spec-text-secondary, #aaaaaa)';
      textSpan.style.marginLeft = '8px';
      textSpan.style.cursor = 'help';
      textSpan.style.display = 'inline-flex';
      textSpan.style.alignItems = 'center';
      textSpan.style.transition = 'color 0.2s ease';
      textSpan.style.fontStyle = '';
      textSpan.style.textShadow = '';

      if (isLowSample) {
        textSpan.style.color = 'var(--yt-spec-text-disabled, #7f8c8d)';
        textSpan.style.fontStyle = 'italic';
      } else {
        if (smoothedRatio >= 6.0) {
          textSpan.style.color = '#f39c12';
          textSpan.style.fontWeight = '500';
          textSpan.style.textShadow = '0 0 2px rgba(243, 156, 18, 0.3)';
        } else if (smoothedRatio >= 3.0) {
          textSpan.style.color = '#2ed573';
          textSpan.style.fontWeight = '500';
        }
      }

      textSpan.textContent = '';
      const dotSpan = document.createElement('span');
      dotSpan.style.marginRight = '8px';
      dotSpan.style.color = 'var(--yt-spec-text-secondary, #aaaaaa)';
      dotSpan.textContent = '•';
      const textNode = document.createTextNode(`👍/👁️ ${ratioFormatted}`);
      textSpan.appendChild(dotSpan);
      textSpan.appendChild(textNode);
    }

    console.log(`[Like-to-View] 渲染成功: ID=${card.dataset.ytVideoId}, 播放量=${views}, 比例=${ratioFormatted}`);
  }

  let hasLoggedScan = false;

  function scanAndProcess() {
    let totalCards = 0;
    let processedCards = 0;
    let missingAnchor = 0;
    let missingId = 0;

    // # [Gemini_3.5_Flash_planning] 使用递归穿透型 shadow DOM 卡片检索
    const cards = findCardsShadow(document.body, CARD_SELECTORS);
    totalCards = cards.length;

    cards.forEach(card => {
      const videoId = findVideoIdInCard(card);
      if (!videoId) {
        // 如果卡片还没有被赋予 videoId，不作标记，下次轮询时重新匹配（防止属性绑定延迟竞争）
        // # [Gemini_3.5_Flash_planning] 诊断日志检查：支持新版卡片的缩略图和锚点判断
        const hasThumb = !!querySelectorShadow(card, 'ytd-thumbnail') || !!querySelectorShadow(card, 'yt-thumbnail-view-model');
        const hasAnchor = !!querySelectorShadow(card, 'a#thumbnail') || !!querySelectorShadow(card, 'a.ytLockupViewModelContentImage');
        if (!hasThumb || !hasAnchor) {
          missingAnchor++;
        } else {
          missingId++;
        }
        return;
      }

      // # [Gemini_3.5_Flash_planning] 漏洞防护：判断当前真实 ID 是否与卡片缓存的 ID 相同。
      // 如果相同，且已被标记为处理，则直接跳过（常规已处理卡片）。
      // 如果不同（说明是 SPA 路由切换引起的 DOM 节点复用），则重新进行数据获取和渲染。
      if (card.dataset.ytVideoId === videoId && card.dataset.ytProcessed === 'true') {
        processedCards++;
        return;
      }

      // 更新（或初始化）卡片的缓存 ID 及状态
      card.dataset.ytVideoId = videoId;
      card.dataset.ytProcessed = 'true';

      // 观察可见性，以触发数据查询
      intersectionObserver.observe(card);
    });

    if (!hasLoggedScan && totalCards > 0) {
      console.log(`[Like-to-View] 诊断报告(Main World): 页面共发现 ${totalCards} 个可能视频卡片。已处理: ${processedCards}。未处理卡片中：找不到缩略图/锚点: ${missingAnchor}，找不到ID或未绑定: ${missingId}`);
      hasLoggedScan = true;
    }
  }

  console.log('[Like-to-View] 核心探针注入Main World成功，启动底层穿透监听。');

  // # [Gemini_3.5_Flash_planning] 降低心跳诊断日志频率，保持控制台整洁
  setInterval(() => {
    const cards = findCardsShadow(document.body, CARD_SELECTORS);
    console.log(`[Like-to-View] 心跳诊断(Main World): 当前匹配到卡片总数 = ${cards.length}`);
  }, 10000);

  setInterval(scanAndProcess, 1000);

})();


