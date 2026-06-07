/**
 * Modification History
 * 
 * Version | Date       | Author               | Description
 * --------|------------|----------------------|----------------------------------------------------
 * 1.0.0   | 2026-06-07 | Gemini_3.5_Flash_fast| 初始创建，使用 Service Worker 代理跨域 API 请求，避开 YouTube 的 CSP 限制
 */

// [Gemini_3.5_Flash_fast] 监听来自 Content Script 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getStats' && request.videoId) {
    // 异步执行 Fetch 并返回结果，绕过页面沙箱的 CSP 限制
    fetch(`https://returnyoutubedislikeapi.com/votes?id=${request.videoId}`)
      .then(response => {
        if (!response.ok) throw new Error('API response not ok');
        return response.json();
      })
      .then(data => {
        sendResponse({ success: true, data });
      })
      .catch(error => {
        sendResponse({ success: false, error: error.message });
      });
    
    // [Gemini_3.5_Flash_fast] 必须返回 true 以启用异步 sendResponse
    return true; 
  }
});
