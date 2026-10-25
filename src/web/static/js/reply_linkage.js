/** 回复额度共用联动控件：计算由服务端负责，保存前等待最新结果。
 * Modification History
 * | Version | Date | Author | Description |
 * | --- | --- | --- | --- |
 * | 1.0.0 | 2026-10-25 | Codex | 双入口共用自动/手动、恢复自动、竞态和容量反馈。 |
 */
(() => {
  'use strict';
  const defaults = {initialized:false,hourly_quota:'auto',min_interval_seconds:'auto'};
  const names = {daily_quota:'最近24小时上限',hourly_quota:'小时上限',min_interval_seconds:'最小间隔'};
  const make = (tag,text) => { const n=document.createElement(tag); if(text)n.textContent=text; return n; };
  window.ReplyLinkage = {mount({host,inputs,get,set,onChange,capacity,original}) {
    let mode={...defaults,...get().linkage},report=capacity,pending=null,controller=null,sequence=0,error='',disposed=false,confirmation=null;
    const statuses={},buttons={},listeners=[];
    const feedback=make('p');feedback.className='hint';feedback.id=host.id+'-capacity';feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');
    const summary=make('p');summary.className='hint';summary.setAttribute('aria-live','polite');
    function syncMode(){set({linkage:{...mode}});}
    function render(){
      for(const key of Object.keys(statuses)) { statuses[key].textContent=mode[key]==='manual'?'手动 · 后续联动保留':'自动 · 随总量和时段联动';buttons[key].disabled=Boolean(pending); }
      feedback.textContent=pending?'正在计算联动与理论容量…':error||report?.message||'理论容量尚未核实';
      feedback.dataset.state=error?'error':report?.insufficient?'warning':'info';
      const value=get(),changes=[];
      for(const key of Object.keys(names))if(value[key]!==original[key])changes.push(`${names[key]} ${original[key]} → ${value[key]}`);
      summary.textContent=changes.length?'待保存：'+changes.join('；'):'当前数值未修改。首次调整总量或恢复自动时采用推荐值。';
      onChange();
    }
    function recompute() {
      controller?.abort();controller=new AbortController();const own=controller,seq=++sequence;
      mode.initialized=true;syncMode();error='';
      const work=(async()=>{
        // 下一微任务再发送，保证页面的输入适配器已完成当前事件更新。
        await Promise.resolve();
        const timer=setTimeout(()=>own.abort(),12000);
        try {
          const response=await fetch('/api/runtime-configuration/reply-recommend',{method:'POST',cache:'no-store',signal:own.signal,
            headers:{'Content-Type':'application/json','X-Runtime-CSRF':document.querySelector('meta[name=runtime-csrf]')?.content||''},body:JSON.stringify({config:get()})});
          const data=await response.json();
          if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'请修正额度或时段后重试');
          if(seq!==sequence||disposed)return;
          set(data.config);mode={...data.config.linkage};report=data.capacity;
        } catch(e) { if(seq===sequence&&!disposed)error=e.name==='AbortError'?'联动计算超时，请修改参数或点击恢复自动重试。':e.message; }
        finally {clearTimeout(timer);if(seq===sequence&&!disposed){pending=null;render();}}
      })();
      pending=work;render();return work;
    }
    const listen=(element,handler)=>{element.addEventListener('input',handler);listeners.push([element,handler]);};
    for(const key of ['hourly_quota','min_interval_seconds']) {
      const line=make('div'),status=make('span'),button=make('button','恢复自动');line.className='reply-linkage-mode';
      status.id=host.id+'-'+key+'-mode';button.id=host.id+'-'+key+'-restore';button.type='button';button.setAttribute('aria-label',names[key]+'恢复自动');
      statuses[key]=status;buttons[key]=button;line.append(status,button);inputs[key].insertAdjacentElement('afterend',line);
      const described=inputs[key].getAttribute('aria-describedby')||'';inputs[key].setAttribute('aria-describedby',(described+' '+status.id+' '+feedback.id).trim());
      button.onclick=()=>{mode[key]='auto';recompute();};
      listen(inputs[key],()=>{mode[key]='manual';recompute();});
    }
    for(const key of ['daily_quota','window_start_shanghai','window_end_shanghai'])if(inputs[key])listen(inputs[key],recompute);
    const reset=make('button','全部恢复自动');reset.type='button';reset.id=host.id+'-restore-all';reset.onclick=()=>{mode={...defaults};recompute();};
    host.replaceChildren(reset,feedback,summary);
    // 仅设置本地初始状态；载入或刷新页面不产生配置修改。
    render();
    return {get mode(){return {...mode};},get pending(){return Boolean(pending);},get error(){return error;},get report(){return report;},
      async settled(){await pending;return !error;},
      dispose(){disposed=true;controller?.abort();listeners.forEach(([el,fn])=>el.removeEventListener('input',fn));Object.values(statuses).forEach(el=>el.parentElement.remove());host.replaceChildren();},
      async confirmCapacity(){
        if(!report?.insufficient)return true;
        if(confirmation)return confirmation;
        confirmation=new Promise(resolve=>{
          const previous=document.activeElement,dialog=make('dialog'),title=make('h2','当前容量低于每日额度'),description=make('p',report.message),foot=make('div'),cancel=make('button','返回调整'),save=make('button','仍保存此配置');
          title.id=host.id+'-warning-title';dialog.setAttribute('aria-labelledby',title.id);foot.className='dialog-foot';cancel.type=save.type='button';foot.append(cancel,save);dialog.append(title,description,foot);document.body.append(dialog);
          let accepted=false;cancel.onclick=()=>dialog.close();save.onclick=()=>{accepted=true;dialog.close();};dialog.addEventListener('close',()=>{dialog.remove();previous?.focus();confirmation=null;resolve(accepted);},{once:true});dialog.showModal();cancel.focus();
        });return confirmation;
      }};
  }};
})();
