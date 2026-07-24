

// Phase 7.4.2 staff analytics charts.
(function(){
  const node=document.getElementById('staff-analytics-data'); if(!node) return;
  const data=JSON.parse(node.textContent||'{}');
  function bars(id, rows, keys){
    const el=document.getElementById(id); if(!el) return;
    if(!rows.length){el.innerHTML='<div class="empty-state compact"><b>No staff data yet</b></div>';return;}
    const max=Math.max(1,...rows.flatMap(r=>keys.map(k=>Number(r[k.key]||0))));
    el.innerHTML='<div class="staff-bar-chart">'+rows.map(r=>'<div class="staff-bar-row"><span title="'+r.label+'">'+r.label+'</span><div>'+keys.map(k=>'<i class="'+k.key+'" style="width:'+Math.max(2,(Number(r[k.key]||0)/max)*100)+'%" title="'+k.label+': '+Number(r[k.key]||0)+'"></i>').join('')+'</div></div>').join('')+'<div class="chart-legend">'+keys.map(k=>'<span><i class="'+k.key+'"></i>'+k.label+'</span>').join('')+'</div></div>';
  }
  bars('staff-workload-chart',data.workload||[],[{key:'open',label:'Open tasks'},{key:'overdue',label:'Overdue'}]);
  bars('staff-activity-chart',data.activity||[],[{key:'activities',label:'Activities'},{key:'completed',label:'Completed tasks'}]);
})();
