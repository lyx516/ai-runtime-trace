function parseRecipients(d) {
  const r = d.intended_recipients;
  if (Array.isArray(r)) return r;
  if (typeof r === 'string') try { return JSON.parse(r); } catch(e) { return [r]; }
  return [];
}

function renderGraph(data) { renderSequenceDiagram(data); }

async function renderSequenceDiagram(g) {
  const dagEl = document.getElementById('graph-dag');
  dagEl.innerHTML = '<div style="color:var(--text-tertiary);padding:12px">Loading timeline ...</div>';
  const states = g.states || [];
  if (!states.length) { dagEl.innerHTML = '<div class="empty-state">No state data</div>'; return; }

  try {
    const [thR, decR, msgR] = await Promise.all([
      fetch('/api/runs/'+currentRunId+'/thinking').then(r=>r.json().catch(()=>[])),
      fetch('/api/runs/'+currentRunId+'/decisions').then(r=>r.json().catch(()=>[])),
      fetch('/api/runs/'+currentRunId+'/messages').then(r=>r.json().catch(()=>[])),
    ]);
    const transitions = g.transitions || [];
    const currentState = g.current_state_id;
    const agents = [];
    const seen = new Set();
    states.forEach(s=>(s.actors||[]).forEach(a=>{if(!seen.has(a)){seen.add(a);agents.push(a);}}));

    const events = [];
    (thR||[]).forEach(t => {
      const st = (t.step_type||'');
      if (st === 'submit_decision') events.push({ts:t.created_at||'', type:'decision', role:t.role_id, state:t.state_id||'', data:t, source:'thinking'});
      else if (st === 'send_message') events.push({ts:t.created_at||'', type:'message', role:t.role_id, state:'', data:t, source:'thinking'});
      else events.push({ts:t.created_at||'', type:'toolCall', role:t.role_id, state:t.state_id||'', data:t, source:'thinking'});
    });
    (decR||[]).forEach(d => events.push({ts:d.created_at||'', type:'decision', role:d.role_id, state:d.state_id||'', data:d, source:'decisions'}));
    (msgR||[]).forEach(m => events.push({ts:m.created_at||'', type:'message', role:m.from_role||m.role_id, state:'', data:m, source:'messages'}));
    transitions.forEach(t => events.push({ts:t.created_at||t.ts||'', type:'transition', role:'gate', state:'', data:t, source:'transitions'}));
    events.sort((a,b)=>(a.ts||'').localeCompare(b.ts||''));
    const currentActors = new Set((states.find(s=>s.state_id===currentState)?.actors||[]));

    const colW = 150, gateW = 120, timeW = 50, rowH = 40;
    let html = '';
    html += '<div style="display:flex;gap:12px;font-size:11px;color:var(--text-tertiary);margin-bottom:6px">Status: <strong style="color:var(--green)">'+g.status+'</strong>  '+states.length+' states  '+transitions.length+' transitions  '+events.length+' events</div>';
    html += '<div style="display:flex;gap:16px;margin-bottom:6px;font-size:10px;color:var(--text-secondary)">' +
      '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#2dd4bf;margin-right:4px"></span>tool</span>' +
      '<span><span style="display:inline-block;width:10px;height:10px;border:2px solid var(--green);border-radius:50%;margin-right:4px"></span>decision</span>' +
      '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#a371f7;margin-right:4px"></span>message</span>' +
      '<span><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--text-tertiary);margin-right:4px"></span>gate</span></div>';

    const totalW = timeW + agents.length*colW + gateW;

    // Sticky header (outside scroll container — sticky to viewport)
    html += '<div id="seq-header-sticky" style="position:sticky;top:0;z-index:20;background:var(--bg-base);overflow:hidden;min-width:'+totalW+'px">';
    html += '<div style="display:flex;align-items:flex-end;border-bottom:2px solid var(--border);margin-bottom:2px;min-width:'+totalW+'px">';
    html += '<div style="width:'+timeW+'px;flex-shrink:0;font-size:9px;color:var(--text-tertiary);padding:0 4px 4px;text-align:center"><span style="font-size:11px;cursor:ns-resize">⣿</span></div>';
    agents.forEach(a => {
      const active = currentActors.has(a);
      html += '<div style="width:'+colW+'px;flex-shrink:0;text-align:center;padding:0 0 4px;border-left:1px solid var(--border)">'+
        '<span id="ctx-'+a+'" style="font-size:12px;font-weight:600;color:'+(active?'var(--accent)':'var(--text-secondary)')+'">'+a+'</span>'+
        (active?'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-left:4px;box-shadow:0 0 4px var(--accent)"></span>':'')+
        '</div>';
    });
    html += '<div style="width:'+gateW+'px;flex-shrink:0;text-align:center;padding:0 0 4px;border-left:1px solid var(--border)">'+
      '<span id="ctx-gate" style="font-size:12px;font-weight:600;color:var(--text-tertiary)">gate</span></div></div>';
    html += '<div id="ctx-row" style="display:none;background:var(--bg-elevated,rgba(255,255,255,0.03));border-bottom:1px solid var(--border);font-size:10px;line-height:1.3;min-width:'+totalW+'px">';
    html += '<div style="display:flex;min-height:28px;align-items:stretch">';
    html += '<div id="ctx-time" style="width:'+timeW+'px;flex-shrink:0;padding:2px 4px;color:var(--accent);font-weight:500;display:flex;align-items:center;justify-content:center;font-size:9px"></div>';
    agents.forEach(a => {
      html += '<div id="ctx-cell-'+a+'" style="width:'+colW+'px;flex-shrink:0;border-left:1px solid var(--border);padding:2px 6px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column;justify-content:center" onclick="showEventDetailForAgent(\''+a+'\')"></div>';
    });
    html += '<div id="ctx-cell-gate" style="width:'+gateW+'px;flex-shrink:0;border-left:1px solid var(--border);padding:2px 6px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column;justify-content:center" onclick="showEventDetailForAgent(\'gate\')"></div>';
    html += '</div></div>';
    html += '</div>'; // end sticky header

    // Scrollable event rows
    html += '<div id="seq-scroll" style="overflow-x:auto">';
    html += '<div id="seq-body" style="min-width:'+totalW+'px;position:relative">';

    // SVG layer
    html += '<svg id="seq-arrows" style="position:absolute;top:32px;left:0;width:100%;height:0;z-index:5;overflow:visible"></svg>';

    // ── Event rows ──
    const arrows = [];
    window._seqEvents = events;
    events.forEach((e, idx) => {
      const yPos = idx * rowH;
      const timeLabel = e.ts ? new Date(e.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
      let col = e.role === 'gate' ? agents.length : agents.indexOf(e.role);
      if (col < 0) col = 0;
      html += '<div class="seq-row" data-idx="'+idx+'" style="display:flex;height:'+rowH+'px;align-items:center;border-bottom:1px solid rgba(255,255,255,0.03);position:relative">';
      html += '<div style="width:'+timeW+'px;flex-shrink:0;font-size:9px;color:var(--text-tertiary);padding:0 4px">'+timeLabel+'</div>';
      for (let c = 0; c <= agents.length; c++) {
        const w = c < agents.length ? colW : gateW;
        const isEventCol = c === col;
        html += '<div style="width:'+w+'px;flex-shrink:0;border-left:1px solid var(--border);position:relative;height:100%">';
        if (c < agents.length) {
          const active = currentActors.has(agents[c]);
          html += '<div style="position:absolute;top:0;bottom:0;left:50%;width:1px;background:'+(active?'var(--accent)':'var(--border)')+';z-index:0"></div>';
        } else {
          html += '<div style="position:absolute;top:0;bottom:0;left:50%;width:1px;background:var(--border);z-index:0"></div>';
        }
        if (isEventCol) html += renderDot(e, idx);
        html += '</div>';
      }
      html += '</div>';
      if (e.type === 'decision' && col < agents.length) {
        const fromX = timeW + col*colW + colW/2;
        const toX = timeW + agents.length*colW + 4;
        const val = e.data.value || 'APPROVE';
        const clr = val === 'APPROVE' || val === 'PASS' ? '#3fb950' : val === 'REQUEST_CHANGES' ? '#d29922' : '#f85149';
        arrows.push({fromX, toX, y:yPos+rowH/2, color:clr, label:val, idx});
      }
    });

    html += '</div></div>';
    dagEl.innerHTML = html;

    // Sync horizontal scroll between header and scrollable content
    const seqScroll = document.getElementById('seq-scroll');
    const seqHeader = document.getElementById('seq-header-sticky');
    if (seqScroll && seqHeader) {
      seqScroll.addEventListener('scroll', function() {
        seqHeader.scrollLeft = this.scrollLeft;
      });
    }
    dagEl.style.position = 'relative';

    // Inject message arrows
    const body = document.getElementById('seq-body');
    if (body) {
      const headerH = 60;
      events.forEach((e, idx) => {
        if (e.type !== 'message') return;
        const col = agents.indexOf(e.role);
        if (col < 0) return;
        const rcpts = parseRecipients(e.data);
        const y = headerH + idx * rowH + rowH / 2;
        rcpts.forEach(targetRole => {
          const tc = agents.indexOf(targetRole);
          if (tc < 0) return;
          const x1 = timeW + col*colW + colW/2;
          const x2 = timeW + tc*colW + colW/2;
          const left = Math.min(x1, x2);
          const w = Math.abs(x2 - x1);
          if (w < 4) return;
          const dir = tc > col ? 'right' : 'left';
          const arrow = document.createElement('div');
          arrow.style.cssText = 'position:absolute;left:'+left+'px;top:'+(y-1)+'px;width:'+w+'px;height:2px;background:#a371f7;z-index:100;pointer-events:none';
          const head = document.createElement('div');
          head.style.cssText = 'position:absolute;'+(dir==='right'?'right:0':'left:0')+';top:-4px;width:0;height:0;border-'+(dir==='right'?'left':'right')+':6px solid #a371f7;border-top:4px solid transparent;border-bottom:4px solid transparent';
          arrow.appendChild(head);
          const lbl = document.createElement('div');
          lbl.style.cssText = 'position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:9px;color:#a371f7;white-space:nowrap;cursor:pointer;z-index:101';
          lbl.textContent = e.data.kind || 'msg';
          lbl.onclick = () => showEventDetail(idx);
          arrow.appendChild(lbl);
          body.appendChild(arrow);
        });
      });
    }

    window._seqArrows = arrows;
    window._seqAgents = agents;
    window._seqColW = colW;
    window._seqGateW = gateW;
    window._seqTimeW = timeW;
    window._seqRowH = rowH;

    // Inject vertical slider over time gutter
    const bodyEl = document.getElementById('seq-body');
    const firstRow = bodyEl ? bodyEl.querySelector('.seq-row') : null;
    const lastRow = bodyEl ? bodyEl.querySelectorAll('.seq-row') : null;
    if (bodyEl && firstRow && lastRow && lastRow.length > 0) {
      const totalH = events.length * rowH;
      const thumb = document.createElement('div');
      thumb.id = 'slider-thumb';
      thumb.style.cssText = 'position:fixed;left:0;top:50%;width:18px;height:18px;background:var(--accent);border-radius:50%;z-index:999;cursor:ns-resize;box-shadow:0 0 8px rgba(0,0,0,0.4);transform:translateY(-50%)';
      document.body.appendChild(thumb);
    }

    setTimeout(drawArrows, 30);
    setTimeout(() => initSlider(events.length, timeW), 50);

  } catch(e) {
    dagEl.innerHTML = '<div style="color:var(--red);padding:12px">'+e.message+'</div>';
  }
}

// ── Slider (vertical track on time gutter) ──
// ── Slider (fixed-position thumb on left edge) ──

function initSlider(eventCount) {
  const thumb = document.getElementById('slider-thumb');
  const ctxRow = document.getElementById('ctx-row');
  if (!thumb || !ctxRow) return;

  ctxRow.style.display = 'block';
  const svg = document.getElementById('seq-arrows');
  if (svg) svg.style.top = '60px';

  let dragging = false;
  let currentIdx = -1;
  window._sliderCurrentIdx = -1;

  function clientYtoIdx(clientY) {
    const rows = document.querySelectorAll('.seq-row');
    if (!rows.length) return 0;
    let best = 0, bestDist = Infinity;
    rows.forEach((row, i) => {
      const r = row.getBoundingClientRect();
      const d = Math.abs(clientY - (r.top + r.height / 2));
      if (d < bestDist) { bestDist = d; best = i; }
    });
    return best;
  }

  function updateSlider(idx) {
    if (idx < 0 || idx >= eventCount) return;
    currentIdx = idx;
    window._sliderCurrentIdx = idx;
    const row = document.querySelectorAll('.seq-row')[idx];
    if (!row) return;
    const r = row.getBoundingClientRect();
    thumb.style.top = (r.top + r.height / 2) + 'px';
    updateContextBars(idx);
  }

  function updateContextBars(idx) {
    const events = window._seqEvents || [];
    const agents = window._seqAgents || [];
    const latest = {};
    for (let i = 0; i <= idx; i++) { const e = events[i]; if (!e) continue; if (e.role === 'gate') latest['gate'] = e; else latest[e.role] = e; }
    const c = document.getElementById('ctx-time');
    if (c) c.textContent = events[idx]?.ts ? new Date(events[idx].ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
    agents.forEach(a => {
      const cell = document.getElementById('ctx-cell-'+a); if (!cell) return;
      const e = latest[a]; if (!e) { cell.innerHTML = '<span style="color:var(--text-tertiary);font-size:9px">—</span>'; return; }
      const d = e.data;
      let info = '';
      if (e.type === 'toolCall') info = '<div style="color:#2dd4bf">● '+(d.step_type||'').replace(/_/g,' ')+'</div>'+(e.state?'<div style="color:var(--text-tertiary);font-size:8px">@'+e.state+'</div>':'')+'<div style="color:var(--text-tertiary);font-size:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(d.output?JSON.stringify(d.output).slice(0,40):'')+'</div>';
      else if (e.type === 'decision') { const clr = d.value==='APPROVE'?'var(--green)':d.value==='REQUEST_CHANGES'?'var(--yellow)':'var(--red)'; info = '<div style="color:'+clr+'">◯ '+d.value+'</div>'+(e.state?'<div style="color:var(--text-tertiary);font-size:8px">@'+e.state+'</div>':'')+'<div style="color:var(--text-tertiary);font-size:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(d.reason||'').slice(0,40)+'</div>'; }
      else if (e.type === 'message') info = '<div style="color:#a371f7">→ ['+parseRecipients(d).join(',')+']</div><div style="color:var(--text-tertiary);font-size:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(d.content||'').slice(0,40)+'</div>';
      cell.innerHTML = info;
    });
    const gc = document.getElementById('ctx-cell-gate');
    if (gc) {
      const e = latest['gate'];
      gc.innerHTML = e ? '<div style="color:var(--text-tertiary)">● '+(e.data.to||'→')+'</div><div style="color:var(--text-tertiary);font-size:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(e.data.gate_result||'').slice(0,40)+'</div>' : '<span style="color:var(--text-tertiary);font-size:9px">—</span>';
    }
  }

  // Drag from thumb
  thumb.addEventListener('pointerdown', e => { dragging = true; thumb.setPointerCapture(e.pointerId); e.preventDefault(); });
  thumb.addEventListener('pointermove', e => { if (dragging) updateSlider(clientYtoIdx(e.clientY)); });
  thumb.addEventListener('pointerup', e => { if (dragging) { dragging = false; updateSlider(currentIdx); } });
  thumb.addEventListener('pointercancel', e => { if (dragging) { dragging = false; } });

  if (eventCount > 0) updateSlider(0);
}

// ── Event detail popup for context bar click ──

window.showEventDetailForAgent = function(role) {
  const idx = window._sliderCurrentIdx;
  if (idx < 0 || !window._seqEvents) return;
  const events = window._seqEvents;
  // Find latest event for this role at or before current idx
  for (let i = idx; i >= 0; i--) {
    const e = events[i];
    if (!e) continue;
    if ((role === 'gate' && e.role === 'gate') || e.role === role) {
      showEventDetail(i);
      return;
    }
  }
};

// ── Dot renderer ──

function renderDot(e, idx) {
  const tip = (e.data.step_type||e.type).replace(/_/g,' ');
  const click = 'showEventDetail('+idx+')';
  if (e.type === 'toolCall') {
    return '<div onclick="'+click+'" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2;cursor:pointer" title="'+tip+'">'+
      '<div style="width:8px;height:8px;border-radius:50%;background:#2dd4bf;border:2px solid var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;left:14px;transform:translateY(-50%);font-size:9px;color:#2dd4bf;white-space:nowrap;pointer-events:none">'+tip+'</div></div>';
  }
  if (e.type === 'decision') {
    const val = e.data.value||'APPROVE';
    const clr = val==='APPROVE'||val==='PASS'?'var(--green)':val==='REQUEST_CHANGES'?'var(--yellow)':'var(--red)';
    return '<div onclick="'+click+'" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2;cursor:pointer" title="decision: '+val+'">'+
      '<div style="width:12px;height:12px;border:2px solid '+clr+';border-radius:50%;background:var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;right:14px;transform:translateY(-50%);font-size:10px;font-weight:600;color:'+clr+';white-space:nowrap;pointer-events:none">'+val+'</div></div>';
  }
  if (e.type === 'message') {
    const rcpts = parseRecipients(e.data).join(',');
    return '<div onclick="'+click+'" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2;cursor:pointer" title="message to ['+rcpts+']">'+
      '<div style="width:10px;height:10px;border-radius:50%;background:#a371f7;border:2px solid var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;right:14px;transform:translateY(-50%);font-size:9px;color:#a371f7;white-space:nowrap;pointer-events:none">→ ['+rcpts+']</div></div>';
  }
  if (e.type === 'transition') {
    const to = e.data.to||'→';
    return '<div onclick="'+click+'" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2;cursor:pointer" title="transition: '+to+'">'+
      '<div style="width:6px;height:6px;border-radius:50%;background:var(--text-tertiary);border:2px solid var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;left:14px;transform:translateY(-50%);font-size:9px;color:var(--text-tertiary);white-space:nowrap;pointer-events:none">→ '+to+'</div></div>';
  }
  return '';
}

// ── SVG arrows ──

function drawArrows() {
  const svg = document.getElementById('seq-arrows');
  if (!svg) return;
  const arrows = window._seqArrows || [];
  if (!arrows.length) { svg.setAttribute('height','0'); return; }
  const h = (window._seqEvents.length||0) * 40 + 10;
  svg.setAttribute('height', h);
  svg.innerHTML = '';
  svg.style.pointerEvents = 'none';
  arrows.forEach(a => {
    const g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.style.cursor = 'pointer';
    g.style.pointerEvents = 'auto';
    g.addEventListener('click', ()=>showEventDetail(a.idx));
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1', a.fromX); line.setAttribute('y1', a.y);
    line.setAttribute('x2', a.toX); line.setAttribute('y2', a.y);
    line.setAttribute('stroke', a.color); line.setAttribute('stroke-width', '2');
    g.appendChild(line);
    const hd = document.createElementNS('http://www.w3.org/2000/svg','polygon');
    const sz = 5;
    hd.setAttribute('points', (a.toX-2)+','+(a.y-sz)+' '+(a.toX+4)+','+a.y+' '+(a.toX-2)+','+(a.y+sz));
    hd.setAttribute('fill', a.color);
    g.appendChild(hd);
    if (a.label) {
      const txt = document.createElementNS('http://www.w3.org/2000/svg','text');
      txt.setAttribute('x', (a.fromX+a.toX)/2);
      txt.setAttribute('y', a.y-6);
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('fill', a.color);
      txt.setAttribute('font-size', '10');
      txt.setAttribute('font-weight', '500');
      txt.setAttribute('font-family', 'system-ui,sans-serif');
      txt.textContent = a.label;
      g.appendChild(txt);
    }
    svg.appendChild(g);
  });
}

// ── Event detail popup ──

function showEventDetail(idx) {
  const e = (window._seqEvents||[])[idx];
  if (!e) return;
  const panel = document.getElementById('graph-panel');
  panel.style.display = 'block';
  const d = e.data;
  let title='', fields=[];

  if (e.type === 'toolCall') {
    title = 'Tool Call — '+(d.step_type||'').replace(/_/g,' ');
    fields = [
      {l:'Agent', v:d.role_id},{l:'Tool', v:(d.step_type||'').replace(/_/g,' ')},
      {l:'State', v:e.state||'-'},{l:'Inputs', v:JSON.stringify(d.inputs||{},null,2), m:true},
      {l:'Output', v:JSON.stringify(d.output||{},null,2), m:true},
      {l:'Time', v:d.created_at?new Date(d.created_at).toLocaleString():''},
    ];
  } else if (e.type === 'decision') {
    title = 'Decision — '+d.value;
    fields = [
      {l:'Agent', v:d.role_id},{l:'Value', v:d.value},{l:'State', v:d.state_id},
      {l:'Reason', v:d.reason||'(none)'},
      {l:'Time', v:d.created_at?new Date(d.created_at).toLocaleString():''},
    ];
  } else if (e.type === 'message') {
    title = 'Message';
    fields = [
      {l:'From', v:d.from_role||d.role_id},{l:'To', v:parseRecipients(d).join(', ')||'(broadcast)'},
      {l:'Kind', v:d.kind||''},{l:'Content', v:d.content||'(empty)'},
      {l:'Time', v:d.created_at?new Date(d.created_at).toLocaleString():''},
    ];
  } else if (e.type === 'transition') {
    title = 'Transition — '+d.from+' → '+d.to;
    fields = [
      {l:'From', v:d.from},{l:'To', v:d.to},{l:'Gate', v:d.gate_result||'auto'},
      {l:'Round', v:(d.round||0)+1},
      {l:'Time', v:d.created_at?new Date(d.created_at).toLocaleString():''},
    ];
  }

  let ph = '<div style="border-left:3px solid var(--accent);padding-left:12px">'+
    '<h3 style="font-size:14px;font-weight:600;margin:0 0 8px">'+title+'</h3>';
  fields.forEach(f=>{
    ph += '<div style="margin-bottom:4px">'+
      '<span style="font-size:10px;color:var(--text-tertiary);display:block">'+f.l+'</span>'+
      '<span style="font-size:12px;color:var(--text-primary);'+(f.m?'font-family:monospace;white-space:pre-wrap':'')+'">'+(f.v||'')+'</span></div>';
  });
  ph += '</div>';
  panel.innerHTML = ph;
}
