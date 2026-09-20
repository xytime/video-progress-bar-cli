"""真实隔离 Chromium 中的视频号位置选择验收。

# Modification History
| Version | Date       | Author | Description |
|---------|------------|--------|-------------|
| 1.0.0   | 2026-09-20 | Codex  | 按真实发布页 DOM 验证“不显示位置”的展开、点击与显示区回读。 |
"""

from scripts.wechat_uploader import _select_no_location
from tests.browser_fixtures import chromium


def test_select_no_location_against_wechat_form_dom(chromium):
    page = chromium.new_page(viewport={"width": 1200, "height": 500})
    try:
        page.set_content("""
          <div class="form-item">
            <div class="label">位置</div>
            <div class="form-item-body">
              <div class="post-position-wrap">
                <div class="position-display">
                  <div class="position-display-wrap">
                    <div class="place"><span class="location-name">北京市</span></div>
                  </div>
                </div>
                <div class="location-filter-wrap" style="display:none">
                  <div class="common-option-list-wrap">
                    <div class="option-item"><div class="name">不显示位置</div></div>
                    <div class="option-item"><div class="name">北京市</div></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <script>
            const dropdown = document.querySelector('.location-filter-wrap');
            document.querySelector('.position-display').addEventListener('click', () => {
              dropdown.style.display = 'block';
            });
            document.querySelector('.option-item').addEventListener('click', () => {
              document.querySelector('.location-name').textContent = '不显示位置';
              dropdown.style.display = 'none';
            });
          </script>
        """)

        assert _select_no_location(page) is True
        assert page.locator(".location-name").inner_text() == "不显示位置"
        assert not page.locator(".location-filter-wrap").is_visible()
    finally:
        page.close()
