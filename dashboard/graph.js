function parseRecipients(d) {
  if (!d || typeof d !== 'object') return [];
  const readList = v => {
    if (Array.isArray(v)) return v;
    if (typeof v === 'string') {
      if (!v) return [];
      try {
        const parsed = JSON.parse(v);
        return Array.isArray(parsed) ? parsed : [parsed];
      } catch(e) {
        return [v];
      }
    }
    return [];
  };
  const candidates = [
    d.intended_recipients,
    d.authorized_recipients,
    d.recipients,
    d.output && d.output.authorized_recipients,
    d.output && d.output.recipients,
    d.output && d.output.intended_recipients,
    d.inputs && d.inputs.intended_recipients,
    d.inputs && d.inputs.recipients,
  ];
  for (const c of candidates) {
    const values = readList(c).filter(Boolean);
    if (values.length) return values;
  }
  return [];
}

function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function formatJson(v) {
  if (v === undefined || v === null || v === '') return '';
  if (typeof v === 'string') return v;
  try { return JSON.stringify(v, null, 2); } catch(e) { return String(v); }
}

function cleanupSequenceUi() {
  if (typeof window._seqCleanup === 'function') {
    try { window._seqCleanup(); } catch(e) {}
  }
  window._seqCleanup = null;
  document.getElementById('slider-track')?.remove();
  document.getElementById('slider-thumb')?.remove();
  document.getElementById('seq-current-highlight')?.remove();
  window._seqEvents = [];
  window._seqArrows = [];
  window._sliderCurrentIdx = -1;
  window._ctxExpanded = false;
  if (typeof window.clearAgentContextCache === 'function') window.clearAgentContextCache();
}

function normalizeEvents(thinkingRows, decisionRows, messageRows, transitionRows) {
  const events = [];
  const decisionsById = new Map();
  const messagesById = new Map();

  (decisionRows || []).forEach(d => {
    const event = {
      ts: d.created_at || '',
      type: 'decision',
      role: d.role_id,
      state: d.state_id || '',
      data: {...d, thinking_events: []},
      source: 'decisions',
    };
    if (d.decision_id) decisionsById.set(d.decision_id, event);
    events.push(event);
  });

  (messageRows || []).forEach(m => {
    const event = {
      ts: m.created_at || '',
      type: 'message',
      role: m.from_role || m.role_id,
      state: m.state_id || '',
      data: {...m, thinking_events: []},
      source: 'messages',
    };
    if (m.message_id) messagesById.set(m.message_id, event);
    events.push(event);
  });

  (thinkingRows || []).forEach(t => {
    const st = t.step_type || '';
    if (st === 'submit_decision') {
      const id = t.output && t.output.decision_id;
      const canonical = id ? decisionsById.get(id) : null;
      if (canonical) canonical.data.thinking_events.push(t);
      else events.push({ts:t.created_at||'', type:'toolCall', role:t.role_id, state:t.state_id||'', data:t, source:'thinking'});
    } else if (st === 'send_message') {
      const id = t.output && t.output.message_id;
      const canonical = id ? messagesById.get(id) : null;
      if (canonical) canonical.data.thinking_events.push(t);
      else events.push({ts:t.created_at||'', type:'toolCall', role:t.role_id, state:t.state_id||'', data:t, source:'thinking'});
    } else {
      events.push({ts:t.created_at||'', type:'toolCall', role:t.role_id, state:t.state_id||'', data:t, source:'thinking'});
    }
  });

  (transitionRows || []).forEach(t => {
    events.push({ts:t.created_at||t.ts||'', type:'transition', role:'gate', state:t.to || t.to_state_id || '', data:t, source:'transitions'});
  });
  events.sort((a,b)=>(a.ts||'').localeCompare(b.ts||''));
  return events;
}

function renderGraph(data) { renderSequenceDiagram(data); }

async function renderSequenceDiagram(g) {
  const dagEl = document.getElementById('graph-dag');
  cleanupSequenceUi();
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

    const events = normalizeEvents(thR, decR, msgR, transitions);
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
    html += '<div id="ctx-row" style="display:none;background:var(--bg-elevated,rgba(255,255,255,0.03));border-bottom:1px solid var(--border);font-size:10px;line-height:1.35;min-width:'+totalW+'px">';
    html += '<div style="display:flex;min-height:56px;align-items:stretch">';
    html += '<div id="ctx-time" style="width:'+timeW+'px;flex-shrink:0;padding:4px;color:var(--accent);font-weight:500;display:flex;align-items:center;justify-content:center;font-size:9px;text-align:center"></div>';
    agents.forEach(a => {
      html += '<div id="ctx-cell-'+a+'" style="width:'+colW+'px;flex-shrink:0;border-left:1px solid var(--border);padding:4px 6px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column;justify-content:flex-start" onclick="toggleAgentContexts()" title="Click to expand full context up to current time"></div>';
    });
    html += '<div id="ctx-cell-gate" style="width:'+gateW+'px;flex-shrink:0;border-left:1px solid var(--border);padding:4px 6px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column;justify-content:flex-start" onclick="toggleAgentContexts()" title="Click to expand full context up to current time"></div>';
    html += '</div></div>';
    html += '<div id="ctx-detail-row" style="display:none;background:rgba(12,14,18,0.98);border-bottom:1px solid var(--border-accent);max-height:42vh;overflow:auto;min-width:'+totalW+'px"></div>';
    html += '</div>'; // end sticky header

    // Scrollable event rows
    html += '<div id="seq-scroll" style="overflow-x:auto;position:relative;z-index:0">';
    html += '<div id="seq-body" style="min-width:'+totalW+'px;position:relative">';

    // SVG layer
    html += '<svg id="seq-arrows" style="position:absolute;top:32px;left:0;width:100%;height:0;z-index:1;overflow:visible;pointer-events:none"></svg>';

    // ── Event rows ──
    const arrows = [];
    window._seqEvents = events;
    window._ctxExpanded = false;
    events.forEach((e, idx) => {
      const yPos = idx * rowH;
      const timeLabel = e.ts ? new Date(e.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
      let col = e.role === 'gate' ? agents.length : agents.indexOf(e.role);
      if (col < 0) col = 0;
      html += '<div class="seq-row" data-idx="'+idx+'" style="display:flex;height:'+rowH+'px;align-items:center;border-bottom:1px solid rgba(255,255,255,0.03);position:relative;z-index:2">';
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
          arrow.style.cssText = 'position:absolute;left:'+left+'px;top:'+(y-1)+'px;width:'+w+'px;height:2px;background:#a371f7;z-index:1;pointer-events:none';
          const head = document.createElement('div');
          head.style.cssText = 'position:absolute;'+(dir==='right'?'right:0':'left:0')+';top:-4px;width:0;height:0;border-'+(dir==='right'?'left':'right')+':6px solid #a371f7;border-top:4px solid transparent;border-bottom:4px solid transparent';
          arrow.appendChild(head);
          const lbl = document.createElement('div');
          lbl.style.cssText = 'position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:9px;color:#a371f7;white-space:nowrap;pointer-events:none';
          lbl.textContent = e.data.kind || 'msg';
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

    setTimeout(drawArrows, 30);
    setTimeout(() => initSlider(events.length, timeW), 50);

  } catch(e) {
    dagEl.innerHTML = '<div style="color:var(--red);padding:12px">'+e.message+'</div>';
  }
}

// ── Slider (vertical track on time gutter) ──
// ── Slider (fixed-position thumb on left edge) ──

function initSlider(eventCount) {
  let track = document.getElementById('slider-track');
  if (!track) {
    track = document.createElement('div');
    track.id = 'slider-track';
    track.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;z-index:998;cursor:ns-resize;touch-action:none;user-select:none;-webkit-user-select:none;overscroll-behavior:contain;background:rgba(88,166,255,0.06);border-left:1px solid rgba(88,166,255,0.18);border-right:1px solid rgba(88,166,255,0.18)';
    track.innerHTML = '<div id="slider-thumb" style="position:absolute;left:50%;top:0;width:18px;height:18px;background:var(--accent);border-radius:50%;z-index:999;cursor:inherit;box-shadow:0 0 8px rgba(0,0,0,0.4);transform:translate(-50%,-50%);pointer-events:none"></div>';
    document.body.appendChild(track);
  }
  let highlight = document.getElementById('seq-current-highlight');
  if (!highlight) {
    highlight = document.createElement('div');
    highlight.id = 'seq-current-highlight';
    highlight.style.cssText = 'position:fixed;left:0;top:0;width:0;height:40px;z-index:12;pointer-events:none;background:rgba(88,166,255,0.12);border-top:1px solid rgba(88,166,255,0.28);border-bottom:1px solid rgba(88,166,255,0.20);box-shadow:0 0 16px rgba(88,166,255,0.08);display:none';
    document.body.appendChild(highlight);
  }
  const thumb = document.getElementById('slider-thumb');
  const ctxRow = document.getElementById('ctx-row');
  if (!track || !thumb || !highlight || !ctxRow) return;

  ctxRow.style.display = 'block';
  const svg = document.getElementById('seq-arrows');
  if (svg) svg.style.top = '60px';

  let dragging = false;
  let currentIdx = -1;
  let restoreBodyOverflow = '';
  let restoreHtmlOverflow = '';
  let restoreContentOverflow = '';
  let trackAnchorTop = null;
  let trackAnchorHeight = null;
  window._sliderCurrentIdx = -1;

  const scroller = document.getElementById('main-content');

  function positionTrack() {
    const seqScroll = document.getElementById('seq-scroll');
    const header = document.getElementById('seq-header-sticky');
    const timeHeaderCell = header?.children[0]?.children[0];
    const scrollerRect = scroller?.getBoundingClientRect();
    const seqRect = seqScroll?.getBoundingClientRect();
    const cellRect = (timeHeaderCell || document.querySelector('.seq-row')?.children[0])?.getBoundingClientRect();
    if (!scrollerRect || !seqRect || !cellRect) return;

    const headerBottom = header ? header.getBoundingClientRect().bottom : scrollerRect.top;
    if (trackAnchorTop === null || trackAnchorHeight === null) {
      const top = Math.max(scrollerRect.top, Math.min(headerBottom, scrollerRect.bottom - 24));
      trackAnchorTop = top;
      trackAnchorHeight = Math.max(24, scrollerRect.bottom - top);
    }
    track.style.left = cellRect.left + 'px';
    track.style.top = trackAnchorTop + 'px';
    track.style.width = cellRect.width + 'px';
    track.style.height = trackAnchorHeight + 'px';

    highlight.style.left = Math.max(cellRect.left, seqRect.left) + 'px';
    highlight.style.width = Math.max(0, Math.min(seqRect.right, window.innerWidth) - Math.max(cellRect.left, seqRect.left)) + 'px';
  }

  function renderThumb(idx) {
    positionTrack();
    const tr = track.getBoundingClientRect();
    const denom = Math.max(1, eventCount - 1);
    const y = (Math.max(0, Math.min(eventCount - 1, idx)) / denom) * tr.height;
    thumb.style.top = y + 'px';
    const rowH = window._seqRowH || 40;
    highlight.style.top = (tr.top + y - rowH / 2) + 'px';
    highlight.style.height = rowH + 'px';
    highlight.style.display = 'block';
  }

  function clientYtoIdx(clientY) {
    positionTrack();
    const tr = track.getBoundingClientRect();
    if (!tr.height || eventCount <= 1) return 0;
    const pct = Math.max(0, Math.min(1, (clientY - tr.top) / tr.height));
    return Math.round(pct * (eventCount - 1));
  }

  function scrollSelectedRowIntoView(idx) {
    if (!scroller) return;
    const row = document.querySelectorAll('.seq-row')[idx];
    if (!row) return;
    const rr = row.getBoundingClientRect();
    const sr = scroller.getBoundingClientRect();
    const targetY = sr.top + sr.height * 0.45;
    scroller.scrollTo({top: scroller.scrollTop + rr.top + rr.height / 2 - targetY, behavior: 'auto'});
  }

  function updateSlider(idx, scrollIntoView = false) {
    if (idx < 0 || idx >= eventCount) return;
    currentIdx = idx;
    window._sliderCurrentIdx = idx;
    if (scrollIntoView) scrollSelectedRowIntoView(idx);
    renderThumb(idx);
    updateContextBars(idx);
  }

  function updateContextBars(idx) {
    const events = window._seqEvents || [];
    const agents = window._seqAgents || [];
    const latest = {};
    for (let i = 0; i <= idx; i++) { const e = events[i]; if (!e) continue; if (e.role === 'gate') latest['gate'] = e; else latest[e.role] = e; }
    const c = document.getElementById('ctx-time');
    if (c) c.innerHTML = '<div>'+escapeHtml(events[idx]?.ts ? new Date(events[idx].ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '')+'</div><div style="font-size:8px;color:var(--text-tertiary);margin-top:3px">ctx</div>';
    agents.forEach(a => {
      const cell = document.getElementById('ctx-cell-'+a); if (!cell) return;
      const e = latest[a]; if (!e) { cell.innerHTML = '<span style="color:var(--text-tertiary);font-size:9px">—</span>'; return; }
      cell.innerHTML = renderContextSummary(e);
    });
    const gc = document.getElementById('ctx-cell-gate');
    if (gc) {
      const e = latest['gate'];
      gc.innerHTML = e ? renderContextSummary(e) : '<span style="color:var(--text-tertiary);font-size:9px">—</span>';
    }
    if (window._ctxExpanded) renderAgentContexts(idx);
  }

  function eventColor(e) {
    if (e.type === 'toolCall') return '#2dd4bf';
    if (e.type === 'message') return '#a371f7';
    if (e.type === 'transition') return 'var(--text-tertiary)';
    const v = e.data.value || '';
    return v === 'APPROVE' || v === 'PASS' ? 'var(--green)' : v === 'REQUEST_CHANGES' ? 'var(--yellow)' : 'var(--red)';
  }

  function eventTitle(e) {
    const d = e.data || {};
    if (e.type === 'toolCall') return 'tool: '+(d.step_type || '').replace(/_/g, ' ');
    if (e.type === 'decision') return 'decision: '+(d.value || '');
    if (e.type === 'message') return 'message → ['+parseRecipients(d).join(',')+']';
    return 'transition: '+(d.from || '')+' → '+(d.to || '');
  }

  function eventBody(e) {
    const d = e.data || {};
    if (e.type === 'toolCall') return formatJson(d.output || d.inputs || {});
    if (e.type === 'decision') return d.reason || d.source_references || '';
    if (e.type === 'message') return d.content || formatJson(d.output || d.inputs || {});
    return d.gate_result || d.reason || '';
  }

  function renderContextSummary(e) {
    const body = eventBody(e);
    return '<div style="color:'+eventColor(e)+';font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+escapeHtml(eventTitle(e))+'</div>'+
      (e.state?'<div style="color:var(--text-tertiary);font-size:8px">@'+escapeHtml(e.state)+'</div>':'')+
      '<div style="color:var(--text-secondary);font-size:9px;max-height:30px;overflow:hidden;white-space:normal">'+escapeHtml(body).slice(0,180)+'</div>';
  }

  function addContextItem(ctx, role, e, label, eventIdx) {
    if (!ctx[role]) ctx[role] = [];
    ctx[role].push({event:e, label, eventIdx});
  }

  function buildContextByRole() {
    const events = window._seqEvents || [];
    const roles = [...(window._seqAgents || []), 'gate'];
    const ctx = Object.fromEntries(roles.map(r => [r, []]));
    for (let i = 0; i < events.length; i++) {
      const e = events[i]; if (!e) continue;
      if (e.type === 'message') {
        addContextItem(ctx, e.role, e, 'sent', i);
        parseRecipients(e.data).forEach(r => addContextItem(ctx, r, e, 'inbox', i));
      } else if (e.role === 'gate') {
        addContextItem(ctx, 'gate', e, 'transition', i);
      } else {
        addContextItem(ctx, e.role, e, e.type, i);
      }
    }
    return ctx;
  }

  function contextFocusIndex(items, idx) {
    let focus = -1;
    items.forEach((item, n) => { if (item.eventIdx <= idx) focus = n; });
    return focus;
  }

  function contextRoleId(role) {
    return String(role).replace(/[^a-zA-Z0-9_-]/g, '_');
  }

  function renderAgentContexts(idx) {
    const row = document.getElementById('ctx-detail-row'); if (!row) return;
    const agents = window._seqAgents || [];
    const ctx = buildContextByRole();
    let html = '<div style="display:flex;align-items:stretch;font-size:10px;line-height:1.35">';
    html += '<div style="width:'+window._seqTimeW+'px;flex-shrink:0;padding:6px 4px;color:var(--text-tertiary);text-align:center">all<br>ctx</div>';
    [...agents, 'gate'].forEach(role => {
      const w = role === 'gate' ? window._seqGateW : window._seqColW;
      const items = ctx[role] || [];
      const focus = contextFocusIndex(items, idx);
      html += '<div class="ctx-context-col" data-role="'+escapeHtml(role)+'" style="width:'+w+'px;flex-shrink:0;border-left:1px solid var(--border);padding:6px;max-height:42vh;overflow:auto;scroll-behavior:auto">';
      html += '<div style="font-weight:600;color:'+(role==='gate'?'var(--text-tertiary)':'var(--accent)')+';margin-bottom:6px">'+escapeHtml(role)+' · '+items.length+'</div>';
      if (role !== 'gate') {
        html += '<div class="agent-full-context-slot" data-role="'+escapeHtml(role)+'" data-idx="'+idx+'" style="margin-bottom:8px"></div>';
      }
      if (!items.length) html += '<div style="color:var(--text-tertiary)">No context yet</div>';
      items.forEach((item, n) => {
        const e = item.event;
        const active = n === focus;
        html += '<div class="ctx-context-item'+(active?' current':'')+'" data-event-idx="'+item.eventIdx+'" data-role="'+escapeHtml(contextRoleId(role))+'" style="border-left:3px solid '+eventColor(e)+';padding:5px 6px;margin-bottom:8px;border-radius:4px;background:'+(active?'rgba(88,166,255,0.18)':'transparent')+';box-shadow:'+(active?'inset 0 0 0 1px rgba(88,166,255,0.45)':'none')+'">'+
          '<div style="color:'+eventColor(e)+';font-weight:600">'+(n+1)+'. #'+item.eventIdx+' '+escapeHtml(item.label)+' · '+escapeHtml(eventTitle(e))+(active?' <span style="color:var(--accent);font-size:8px">CURRENT</span>':'')+'</div>'+
          '<pre style="white-space:pre-wrap;word-break:break-word;margin:3px 0 0;color:var(--text-secondary);font-family:SFMono-Regular,monospace;font-size:9px">'+escapeHtml(eventBody(e) || formatJson(e.data))+'</pre>'+
          '</div>';
      });
      html += '</div>';
    });
    html += '</div>';
    row.innerHTML = html;
    row.style.display = 'block';
    if (typeof window.hydrateAgentFullContextSlots === 'function') window.hydrateAgentFullContextSlots();
    requestAnimationFrame(() => {
      row.querySelectorAll('.ctx-context-col').forEach(col => {
        const current = col.querySelector('.ctx-context-item.current');
        if (!current) return;
        col.scrollTop = current.offsetTop - col.clientHeight * 0.35;
      });
    });
  }

  window.toggleAgentContexts = function() {
    window._ctxExpanded = !window._ctxExpanded;
    const row = document.getElementById('ctx-detail-row');
    if (!window._ctxExpanded) { if (row) row.style.display = 'none'; return; }
    renderAgentContexts(window._sliderCurrentIdx >= 0 ? window._sliderCurrentIdx : 0);
  };

  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    try { track.releasePointerCapture(e.pointerId); } catch (_) {}
    document.body.style.overflow = restoreBodyOverflow;
    document.documentElement.style.overflow = restoreHtmlOverflow;
    if (scroller) scroller.style.overflowY = restoreContentOverflow;
    track.style.cursor = 'ns-resize';
    updateSlider(currentIdx);
    e.preventDefault();
  }

  track.addEventListener('pointerdown', e => {
    dragging = true;
    restoreBodyOverflow = document.body.style.overflow;
    restoreHtmlOverflow = document.documentElement.style.overflow;
    restoreContentOverflow = scroller ? scroller.style.overflowY : '';
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    if (scroller) scroller.style.overflowY = 'hidden';
    track.setPointerCapture(e.pointerId);
    track.style.cursor = 'grabbing';
    updateSlider(clientYtoIdx(e.clientY), true);
    e.preventDefault();
  });
  track.addEventListener('pointermove', e => { if (dragging) { updateSlider(clientYtoIdx(e.clientY), true); e.preventDefault(); } });
  track.addEventListener('pointerup', endDrag);
  track.addEventListener('pointercancel', endDrag);
  const onResize = () => { trackAnchorTop = null; trackAnchorHeight = null; renderThumb(currentIdx >= 0 ? currentIdx : 0); };
  const seqScroll = document.getElementById('seq-scroll');
  const onSeqScroll = () => renderThumb(currentIdx >= 0 ? currentIdx : 0);
  const onMainScroll = () => { if (!dragging) renderThumb(currentIdx >= 0 ? currentIdx : 0); };
  window.addEventListener('resize', onResize);
  seqScroll?.addEventListener('scroll', onSeqScroll);
  scroller?.addEventListener('scroll', onMainScroll);
  window._seqCleanup = function() {
    window.removeEventListener('resize', onResize);
    seqScroll?.removeEventListener('scroll', onSeqScroll);
    scroller?.removeEventListener('scroll', onMainScroll);
  };

  if (eventCount > 0) updateSlider(0);
}

// ── Dot renderer ──

function renderDot(e, idx) {
  const tip = (e.data.step_type||e.type).replace(/_/g,' ');
  if (e.type === 'toolCall') {
    return '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2" title="'+tip+'">'+
      '<div style="width:8px;height:8px;border-radius:50%;background:#2dd4bf;border:2px solid var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;left:14px;transform:translateY(-50%);font-size:9px;color:#2dd4bf;white-space:nowrap;pointer-events:none">'+tip+'</div></div>';
  }
  if (e.type === 'decision') {
    const val = e.data.value||'APPROVE';
    const clr = val==='APPROVE'||val==='PASS'?'var(--green)':val==='REQUEST_CHANGES'?'var(--yellow)':'var(--red)';
    return '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2" title="decision: '+val+'">'+
      '<div style="width:12px;height:12px;border:2px solid '+clr+';border-radius:50%;background:var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;right:14px;transform:translateY(-50%);font-size:10px;font-weight:600;color:'+clr+';white-space:nowrap;pointer-events:none">'+val+'</div></div>';
  }
  if (e.type === 'message') {
    const rcpts = parseRecipients(e.data).join(',');
    return '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2" title="message to ['+rcpts+']">'+
      '<div style="width:10px;height:10px;border-radius:50%;background:#a371f7;border:2px solid var(--bg-base)"></div>'+
      '<div style="position:absolute;top:50%;right:14px;transform:translateY(-50%);font-size:9px;color:#a371f7;white-space:nowrap;pointer-events:none">→ ['+rcpts+']</div></div>';
  }
  if (e.type === 'transition') {
    const to = e.data.to||'→';
    return '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2" title="transition: '+to+'">'+
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
    g.style.pointerEvents = 'none';
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


