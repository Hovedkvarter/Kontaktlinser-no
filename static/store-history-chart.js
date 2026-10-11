/* Product history enhancement. Server-rendered chart and price facts remain without JS. */
(function () {
  'use strict';
  const DAY = 86400000, NS = 'http://www.w3.org/2000/svg';
  const colors = ['#2563eb', '#a653b5', '#008e91', '#d44865', '#a57716', '#6670b7', '#387f52', '#a85d36', '#5b8299', '#88507a', '#80762b', '#525f73', '#ad4935', '#357285', '#685c99'];
  const money = v => new Intl.NumberFormat('nb-NO', {maximumFractionDigits: 2}).format(v) + ' kr';
  const day = s => Date.parse(s + 'T00:00:00Z');
  const date = t => new Date(t).toLocaleDateString('nb-NO', {day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
  const shortDate = t => new Date(t).toLocaleDateString('nb-NO', {day:'2-digit',month:'2-digit',timeZone:'UTC'});
  function node(tag, attrs, text) {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key,value]) => el.setAttribute(key,value));
    if (text !== undefined) el.textContent = text;
    return el;
  }
  document.querySelectorAll('.price-intel').forEach(wrap => {
    if (wrap.dataset.storeChartReady) return;
    const panels = [...wrap.querySelectorAll('.price-intel-chart-panel')];
    if (!panels.length || !panels[0].querySelector('.store-chart-data')) return;
    wrap.dataset.storeChartReady = 'true';
    const data = new Map(panels.map(panel => [panel, JSON.parse(panel.querySelector('.store-chart-data').textContent)]));
    const names = [...new Set([...data.values()].flatMap(d => Object.keys(d.stores).filter(name => d.stores[name].some(r => r.price !== null))))].sort((a,b) => a.localeCompare(b,'nb'));
    const selected = new Set(), picker = wrap.querySelector('.store-chart-picker'), chips = wrap.querySelector('.store-chart-selected');
    const color = name => colors[names.indexOf(name) % colors.length];
    const options = picker.querySelector('.store-chart-options');
    names.forEach(name => {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.value = name;
      label.append(input, document.createTextNode(name)); options.append(label);
      input.addEventListener('change', () => { input.checked ? selected.add(name) : selected.delete(name); update(); });
    });
    picker.hidden = !names.length;
    picker.addEventListener('keydown', e => { if (e.key === 'Escape') {picker.open=false;picker.querySelector('summary').focus();} });
    document.addEventListener('click', e => {if (!picker.contains(e.target)) picker.open=false;});
    function update() {
      picker.querySelector('summary').textContent = selected.size ? selected.size + (selected.size===1?' butikk':' butikker') : 'Velg butikk';
      options.querySelectorAll('input').forEach(input => { input.checked=selected.has(input.value); });
      chips.replaceChildren(); chips.hidden = !selected.size;
      selected.forEach(name => {
        const button = document.createElement('button'), dot = document.createElement('i');
        button.type='button'; button.className='store-chart-chip'; button.setAttribute('aria-label','Fjern '+name);
        dot.className='store-chart-swatch'; dot.style.background=color(name);
        button.append(dot,document.createTextNode(name+' ×')); chips.append(button);
        button.addEventListener('click',()=>{selected.delete(name);update();});
      });
      if(selected.size){const clear=document.createElement('button');clear.type='button';clear.className='store-chart-chip';clear.textContent='Tøm';clear.addEventListener('click',()=>{selected.clear();update();});chips.append(clear);}
      panels.forEach(panel=>{if(panel.classList.contains('active')) drawPanel(panel);});
    }
    function drawPanel(panel) {
      const d = data.get(panel), box = panel.querySelector('.price-intel-chart-wrap');
      let tip = box.querySelector('.store-chart-tooltip');
      if(!tip){tip=document.createElement('div');tip.className='store-chart-tooltip';tip.setAttribute('role','status');tip.hidden=true;box.append(tip);}
      tip.hidden=true;
      panel.querySelectorAll('svg.price-history-chart').forEach(svg => {
        const width = svg.getBoundingClientRect().width;
        if(!width) return;
        const mobile = svg.classList.contains('price-intel-chart-mobile'), height = mobile ? Math.max(190,width*205/340) : width*140/680;
        svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
        const left=mobile?48:64,right=12,top=22,bottom=28, plotH=height-top-bottom;
        const start=day(d.lowest[0].date),end=day(d.lowest[d.lowest.length-1].date),span=Math.max(DAY,end-start);
        const lowest={name:'Laveste pris',color:'#f97308',rows:d.lowest};
        const series=[lowest,...[...selected].map(name=>({name,color:color(name),rows:d.stores[name] || []}))];
        const prices=series.flatMap(s=>s.rows.filter(r=>Number.isFinite(r.price)).map(r=>r.price));
        const sorted=[...prices].sort((a,b)=>a-b),median=(sorted[Math.floor((sorted.length-1)/2)]+sorted[Math.floor(sorted.length/2)])/2;
        const min=Math.min(...prices),max=Math.max(...prices),range=Math.max(max-min,25,median*.09),extra=(range-(max-min))/2;
        const lo=min-extra-range*.08,hi=max+extra+range*.08;
        const x=t=>left+(t-start)/span*(width-left-right),y=p=>top+(hi-p)/(hi-lo)*plotH;
        svg.replaceChildren(node('title',{},'Prishistorikk. '+(selected.size?[...selected].join(', '):'Laveste registrerte produktpris per dag')));
        const defs=node('defs'), gradient=node('linearGradient',{id:'storeFade-'+panel.dataset.period+'-'+(mobile?'m':'d'),x1:0,y1:0,x2:0,y2:1});
        gradient.append(node('stop',{offset:'0%','stop-color':'#f97308','stop-opacity':'.17'}),node('stop',{offset:'100%','stop-color':'#f97308','stop-opacity':'.01'}));defs.append(gradient);svg.append(defs);
        let ticks=[];
        for(const step of [1,2,5,10,20,25,50,100,200,250,500,1000,2000,5000]){const vals=[];for(let v=Math.ceil(lo/step)*step;v<=hi;v+=step)vals.push(v);if(vals.length>=3&&vals.length<=5){ticks=vals;break;}}
        if(!ticks.length)ticks=[lo,(lo+hi)/2,hi];
        ticks.forEach(v=>{svg.append(node('line',{x1:left,x2:width-right,y1:y(v),y2:y(v),class:'price-history-gridline'}),node('text',{x:left-8,y:y(v)+4,'text-anchor':'end',fill:'#64748b','font-size':mobile?11:12},money(Math.round(v))));});
        const tickCount=mobile?3:Math.min(8,Math.floor((width-left-right)/95));
        for(let i=0;i<tickCount;i++){const t=start+(end-start)*i/(tickCount-1);svg.append(node('text',{x:x(t),y:height-7,'text-anchor':i===0?'start':i===tickCount-1?'end':'middle',fill:'#64748b','font-size':mobile?11:12},shortDate(t)));}
        series.forEach((s,index)=>{
          const segments=[];let segment=[];
          s.rows.forEach(r=>{if(!Number.isFinite(r.price)){if(segment.length)segments.push(segment);segment=[];return;}if(segment.length&&day(r.date)-day(segment[segment.length-1].date)>DAY){segments.push(segment);segment=[];}segment.push(r);});if(segment.length)segments.push(segment);
          segments.forEach(points=>{
            const line=points.map((r,i)=>(i?'L':'M')+x(day(r.date))+','+y(r.price)).join(' ');
            if(index===0&&points.length>1)svg.append(node('path',{d:line+` L${x(day(points[points.length-1].date))},${height-bottom} L${x(day(points[0].date))},${height-bottom} Z`,fill:`url(#${gradient.id})`}));
            svg.append(node('path',{d:line,fill:'none',stroke:s.color,'stroke-width':1.3,'vector-effect':'non-scaling-stroke'}));
            if(points.length===1)svg.append(node('circle',{cx:x(day(points[0].date)),cy:y(points[0].price),r:2,fill:s.color}));
          });
        });
        const last=d.lowest[d.lowest.length-1];svg.append(node('circle',{cx:x(end),cy:y(last.price),r:3,fill:lowest.color,stroke:'white','stroke-width':1.5}));
        if(!selected.size)svg.append(node('text',{x:x(end),y:Math.max(top+12,y(last.price)-10),'text-anchor':'end',fill:lowest.color,'font-size':13,'font-weight':600},money(last.price)));
        const guide=node('g');svg.append(guide);
        const hit=node('rect',{x:left,y:top,width:Math.max(1,width-left-right),height:plotH,fill:'transparent','pointer-events':'all'});svg.append(hit);
        function hide(){guide.replaceChildren();tip.hidden=true;}
        function show(px,py,keyboard=false){
          const cursorTime=start+(px-left)/(width-left-right)*span;
          const t=start+Math.round((cursorTime-start)/DAY)*DAY;
          const candidates=(selected.size?series.slice(1):[lowest]).map(s=>({s,r:s.rows.find(r=>day(r.date)===t&&Number.isFinite(r.price))})).filter(v=>v.r);
          if(!candidates.length){hide();return;}
          candidates.forEach(c=>{const before=c.s.rows.filter(r=>day(r.date)<=cursorTime).at(-1),after=c.s.rows.find(r=>day(r.date)>=cursorTime);c.hoverY=y(c.r.price);if(before&&after&&Number.isFinite(before.price)&&Number.isFinite(after.price)&&day(after.date)-day(before.date)===DAY){c.hoverY=y(before.price+(after.price-before.price)*(cursorTime-day(before.date))/DAY);}});
          candidates.sort((a,b)=>Math.abs(a.hoverY-py)-Math.abs(b.hoverY-py));const chosen=candidates[0];
          if(selected.size&&!keyboard&&Math.abs(chosen.hoverY-py)>(window.matchMedia('(pointer:coarse)').matches?24:14)){hide();return;}
          const cx=x(t),cy=y(chosen.r.price);
          guide.replaceChildren(node('line',{x1:cx,x2:cx,y1:top,y2:height-bottom,stroke:chosen.s.color,'stroke-width':1,'stroke-dasharray':'4 4'}),node('circle',{cx,cy,r:4,fill:chosen.s.color,stroke:'white','stroke-width':2}));
          const store=document.createElement('span'),price=document.createElement('strong'),when=document.createElement('span');
          store.textContent=selected.size?chosen.s.name:(chosen.r.store||'Laveste pris');price.textContent=money(chosen.r.price);when.textContent=date(t);tip.replaceChildren(store,price,when);tip.hidden=false;
          tip.style.left=Math.max(4,Math.min(width-tip.offsetWidth-4,cx+14))+'px';tip.style.top=Math.max(4,Math.min(height-tip.offsetHeight-4,cy-tip.offsetHeight-14))+'px';
        }
        hit.addEventListener('pointermove',e=>{const r=svg.getBoundingClientRect();show(e.clientX-r.left,e.clientY-r.top);});
        hit.addEventListener('click',e=>{const r=svg.getBoundingClientRect();show(e.clientX-r.left,e.clientY-r.top);});
        hit.addEventListener('pointerleave',e=>{if(e.pointerType!=='touch')hide();});
        let slider=box.querySelector('.store-chart-keyboard');if(!slider){slider=document.createElement('input');slider.type='range';slider.className='store-chart-keyboard';slider.setAttribute('aria-label','Utforsk prishistorikk med piltastene');box.append(slider);}
        slider.min=0;slider.max=Math.round((end-start)/DAY);slider.value=slider.max;
        slider.oninput=()=>{const t=start+Number(slider.value)*DAY;show(x(t),height/2,true);slider.setAttribute('aria-valuetext',tip.hidden?date(t)+', ingen registrert pris':tip.textContent);};
        slider.onfocus=slider.oninput;slider.onblur=hide;
      });
    }
    wrap.querySelectorAll('.price-intel-period-tab[data-period]').forEach(tab=>tab.addEventListener('click',()=>{requestAnimationFrame(update);}));
    let lastWidth=0;new ResizeObserver(entries=>{const width=entries[0].contentRect.width;if(Math.abs(width-lastWidth)>1){lastWidth=width;update();}}).observe(wrap);
    update();
  });
})();
