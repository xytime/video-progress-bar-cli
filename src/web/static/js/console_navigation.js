/* Modification History: 1.0.1 | 2026-10-21 | Codex | 独立预筛选入口与选题分区定位。 */
/** 共享工作台导航。2026-10-12 Codex：v0.3 五区导航、原生抽屉与草稿离开保护。 */
(() => {
  const sections = [
    ['overview', '总览', '/?view=overview', []],
    ['topics', '选题中心', '/?view=topics&tab=waitlist', [
      ['素材待筛选', '/?view=topics&tab=waitlist'], ['近期高互动', '/?view=topics&tab=high_likes'],
      ['视频预筛选', '/video-prefilter'], ['频道白名单', '/?view=operations&tab=channels'], ['YouTube 关键词采集', '/topic-candidates'], ['热词线索', '/?view=topics&tab=hotwords'],
      ['手动加入生产队列', '/?view=topics&tab=manual']]],
    ['production', '生产队列', '/?view=production&tab=queue', []],
    ['publications', '发布记录', '/?view=publications&tab=review', []],
    ['operations', '配置与运维', '/?view=operations', [['生词片尾', '/vocabulary-outro-settings'], ['发布恢复与调度', '/wechat-cooldown-settings']]],
  ];
  const root = location.pathname === '/';
  const rail = document.createElement('aside'); rail.className = 'console-rail';
  const nav = document.createElement('nav'); nav.setAttribute('aria-label', '工作台导航');
  nav.innerHTML = '<a class="console-brand" href="/?view=overview">视频运营工作台</a>' + sections.map(([key,label,href,children]) =>
    `<div class="console-nav-group"><a class="console-primary" data-section="${key}" href="${href}">${label}</a>` +
    (children.length ? `<div class="console-subnav">${children.map(([name,url])=>`<a href="${url}">${name}</a>`).join('')}</div>` : '') + '</div>').join('');
  rail.append(nav); document.body.prepend(rail); document.body.classList.add('console-layout');
  const toggle = document.createElement('button'); toggle.type='button'; toggle.className='console-menu';
  toggle.textContent='导航'; toggle.setAttribute('aria-haspopup','dialog'); toggle.setAttribute('aria-expanded','false');
  document.body.prepend(toggle);
  const drawer=document.createElement('dialog'); drawer.className='console-drawer'; drawer.setAttribute('aria-label','工作台导航');
  const close=document.createElement('button'); close.type='button'; close.textContent='关闭导航';
  drawer.append(close); document.body.append(drawer);
  toggle.onclick=()=>{drawer.append(nav);drawer.showModal();toggle.setAttribute('aria-expanded','true');close.focus();};
  close.onclick=()=>drawer.close();
  drawer.addEventListener('close',()=>{rail.append(nav);toggle.setAttribute('aria-expanded','false');toggle.focus();});
  const wide=matchMedia('(min-width: 1025px)'); wide.addEventListener('change',()=>{if(wide.matches&&drawer.open)drawer.close();});
  function select(view) {
    nav.querySelectorAll('a').forEach(a=>a.removeAttribute('aria-current'));
    const active=nav.querySelector(`[data-section="${view}"]`); if(active)active.setAttribute('aria-current','page');
    nav.querySelectorAll('.console-subnav a').forEach(a=>{
      const url=new URL(a.href);
      if(root ? url.pathname==='/' && url.searchParams.get('tab')===new URL(location.href).searchParams.get('tab') && view==='topics' : url.pathname===location.pathname) a.setAttribute('aria-current','page');
    });
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[href]'); if(!link||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.target)return;
    const url=new URL(link.href); if(url.origin!==location.origin)return;
    if(root&&url.pathname==='/'&&window.DashboardWorkspace){
      event.preventDefault(); if(drawer.open)drawer.close(); window.DashboardWorkspace.navigate(url);
    } else if(window.consoleNavigationGuard && link.closest('.console-rail,.console-drawer')) {
      event.preventDefault(); if(drawer.open)drawer.close(); window.consoleNavigationGuard(()=>location.assign(url.href));
    }
  });
  window.ConsoleNavigation={select};
  select(root ? 'overview' : ['/topic-candidates','/video-prefilter'].includes(location.pathname)?'topics':'operations');
})();
