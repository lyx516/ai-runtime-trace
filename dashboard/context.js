// Agent full-context inspector for the sequence dashboard.
// Loaded by index.html; graph.js injects .agent-full-context-slot elements.

(function() {
  const cache = new Map();

  function h(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function pretty(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value, null, 2); } catch (_) { return String(value); }
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function compact(value, maxLen) {
    const text = pretty(value).replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text;
  }

  function jsonList(value) {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string' && value) {
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [parsed];
      } catch (_) {
        return [value];
      }
    }
    return value ? [value] : [];
  }

  function pill(text, color) {
    const border = color || 'var(--border-accent)';
    return '<span style="display:inline-flex;align-items:center;max-width:100%;padding:2px 6px;border:1px solid '+border+';border-radius:999px;background:rgba(255,255,255,0.035);color:var(--text-secondary);font-size:8px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+h(text)+'</span>';
  }

  function row(label, value) {
    if (value == null || value === '') return '';
    return '<div style="display:grid;grid-template-columns:72px minmax(0,1fr);gap:6px;padding:3px 0;border-top:1px solid rgba(255,255,255,0.045)">'+
      '<div style="color:var(--text-tertiary);font-size:8px;text-transform:uppercase;letter-spacing:.04em">'+h(label)+'</div>'+
      '<div style="color:var(--text-secondary);font-size:9px;min-width:0;overflow-wrap:anywhere">'+h(compact(value, 220))+'</div>'+
      '</div>';
  }

  function rawDetails(title, value) {
    return '<details style="margin-top:6px;border-top:1px solid rgba(255,255,255,0.05);padding-top:5px">'+
      '<summary style="cursor:pointer;color:var(--text-tertiary);font-size:8px">raw '+h(title)+'</summary>'+
      '<pre style="white-space:pre-wrap;word-break:break-word;margin:5px 0 0;color:var(--text-tertiary);font-family:SFMono-Regular,monospace;font-size:8px;line-height:1.45;max-height:180px;overflow:auto">'+h(pretty(value))+'</pre>'+
      '</details>';
  }

  function card(inner, accent) {
    return '<div style="border:1px solid '+(accent || 'rgba(255,255,255,0.08)')+';border-radius:7px;background:rgba(255,255,255,0.025);padding:7px;margin-top:6px;min-width:0">'+inner+'</div>';
  }

  function cardTitle(title, meta, color) {
    return '<div style="display:flex;gap:6px;align-items:center;justify-content:space-between;min-width:0;margin-bottom:4px">'+
      '<div style="font-weight:700;color:'+(color || 'var(--text-primary)')+';font-size:10px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+h(title)+'</div>'+
      '<div style="color:var(--text-tertiary);font-size:8px;white-space:nowrap">'+h(meta || '')+'</div>'+
      '</div>';
  }

  function section(title, rows, renderer) {
    const items = asArray(rows);
    let html = '<section style="margin-top:8px">'+
      '<div style="display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--border);padding-top:7px;margin-bottom:2px">'+
      '<div style="font-weight:700;color:var(--text-primary);font-size:10px">'+h(title)+'</div>'+
      '<div style="color:var(--text-tertiary);font-size:8px">'+items.length+'</div>'+
      '</div>';
    if (!items.length) {
      html += '<div style="color:var(--text-tertiary);font-size:9px;padding:5px 0">empty</div></section>';
      return html;
    }
    html += items.map(renderer).join('') + '</section>';
    return html;
  }

  function renderPacket(packet, data, latestSession, source) {
    const state = data.state_id || packet.state_id || '';
    let html = '<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:5px 0 7px">'+
      pill(source, 'rgba(88,166,255,.45)') +
      pill('state ' + (state || 'unknown')) +
      pill('round ' + (data.round_counter || packet.round_counter || 0));
    if (latestSession) html += pill('session ' + (latestSession.session_id || ''));
    html += '</div>';
    if (packet.state_description) {
      html += '<div style="border-left:2px solid var(--accent);padding-left:7px;margin-bottom:7px;color:var(--text-secondary);font-size:10px;line-height:1.45">'+h(packet.state_description)+'</div>';
    }
    html += card(
      cardTitle('context packet', packet.role_id || data.role_id || '', 'var(--accent)')+
      row('run', packet.run_id || data.run_id)+
      row('role', packet.role_id || data.role_id)+
      row('state', state)+
      row('created', packet.created_at)+
      row('file', latestSession && latestSession.context_file)+
      rawDetails('packet', packet),
      'rgba(88,166,255,0.28)'
    );
    return html;
  }

  function renderMessage(m) {
    const recipients = jsonList(m.intended_recipients || m.authorized_recipients || m.recipients).join(', ');
    const title = (m.from_role || m.role_id || 'message') + (recipients ? ' → ' + recipients : '');
    return card(
      cardTitle(title, m.state_id || '', '#a371f7')+
      '<div style="color:var(--text-primary);font-size:10px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere">'+h(m.content || m.summary || compact(m, 160))+'</div>'+
      row('id', m.message_id)+
      row('kind', m.kind)+
      row('created', m.created_at)+
      rawDetails('message', m),
      'rgba(163,113,247,0.22)'
    );
  }

  function decisionColor(value) {
    if (value === 'APPROVE') return 'var(--green)';
    if (value === 'REQUEST_CHANGES' || value === 'BLOCKED') return 'var(--red)';
    return 'var(--yellow)';
  }

  function renderDecision(d) {
    const color = decisionColor(d.value);
    return card(
      cardTitle((d.role_id || 'decision') + ' · ' + (d.value || ''), d.state_id || '', color)+
      '<div style="color:var(--text-primary);font-size:10px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere">'+h(d.reason || '')+'</div>'+
      row('id', d.decision_id)+
      row('created', d.created_at)+
      rawDetails('decision', d),
      color
    );
  }

  function renderThinking(t) {
    return card(
      cardTitle(t.step_type || 'tool call', t.state_id || '', '#2dd4bf')+
      row('input', t.inputs)+
      row('output', t.output)+
      row('created', t.created_at)+
      rawDetails('thinking', t),
      'rgba(45,212,191,0.22)'
    );
  }

  function renderAudit(a) {
    return card(
      cardTitle(a.event_type || 'audit', a.actor || '', 'var(--text-secondary)')+
      row('state', a.state_id)+
      row('payload', a.payload)+
      row('created', a.created_at)+
      rawDetails('audit', a)
    );
  }

  function latestEventForRole(role, idx) {
    const events = window._seqEvents || [];
    const upto = Number.isFinite(idx) ? Math.min(idx, events.length - 1) : events.length - 1;
    for (let i = upto; i >= 0; i--) {
      const e = events[i];
      if (!e) continue;
      if (e.role === role) return e;
      if (e.type === 'message' && typeof parseRecipients === 'function') {
        try {
          if (parseRecipients(e.data || {}).includes(role)) return e;
        } catch (_) {}
      }
    }
    return events[upto] || null;
  }

  function renderContext(data) {
    if (!data || data.error) {
      return '<div style="color:var(--red)">context error: '+h(data && data.error || 'unknown')+'</div>';
    }
    const packet = data.context_packet || {};
    const sessions = asArray(data.session_contexts);
    const source = data.context_source || 'unknown';
    const latestSession = sessions.length ? sessions[sessions.length - 1] : null;
    let html = '<div style="margin-top:8px;border:1px solid rgba(88,166,255,0.35);border-radius:8px;padding:8px;background:linear-gradient(180deg,rgba(88,166,255,0.075),rgba(88,166,255,0.025));box-shadow:inset 0 1px 0 rgba(255,255,255,0.04)">';
    html += '<div style="font-weight:800;color:var(--accent);font-size:11px;letter-spacing:-.01em">full context</div>';
    html += renderPacket(packet, data, latestSession, source);
    if (typeof window.renderLlmInputContext === 'function') {
      html += window.renderLlmInputContext(data.llm_input, packet);
    }
    html += section('inbox', data.inbox_messages, renderMessage);
    html += section('visible messages', data.visible_messages, renderMessage);
    html += section('decisions seen', data.decisions_seen, renderDecision);
    html += section('thinking / tool calls', data.thinking_events, renderThinking);
    html += section('audit events', data.audit_events, renderAudit);
    html += '</div>';
    return html;
  }

  async function fetchAgentContext(role, idx) {
    const event = latestEventForRole(role, idx);
    const state = event && event.state ? event.state : '';
    const at = event && event.ts ? event.ts : '';
    const runId = window.currentRunId || (typeof currentRunId !== 'undefined' ? currentRunId : '');
    const key = [runId, role, state, at].join('|');
    if (cache.has(key)) return cache.get(key);
    const url = '/api/runs/' + encodeURIComponent(runId) + '/agent-context?role_id=' + encodeURIComponent(role) +
      (state ? '&state_id=' + encodeURIComponent(state) : '') +
      (at ? '&at=' + encodeURIComponent(at) : '');
    const data = await fetch(url).then(async r => {
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
      if (body && body.error) throw new Error(body.error);
      return body;
    });
    cache.set(key, data);
    return data;
  }

  window.hydrateAgentFullContextSlots = function() {
    const slots = document.querySelectorAll('.agent-full-context-slot');
    slots.forEach(slot => {
      const role = slot.dataset.role || '';
      if (!role || role === 'gate') return;
      const idx = Number(slot.dataset.idx || window._sliderCurrentIdx || 0);
      const event = latestEventForRole(role, idx);
      const state = event && event.state ? event.state : '';
      const at = event && event.ts ? event.ts : '';
      const marker = [role, state, at].join('|');
      if (slot.dataset.loadedKey === marker) return;
      slot.dataset.loadedKey = marker;
      slot.innerHTML = '<div style="color:var(--text-tertiary);font-size:9px;margin-top:8px">loading full context...</div>';
      fetchAgentContext(role, idx)
        .then(data => {
          if (slot.dataset.loadedKey !== marker) return;
          slot.innerHTML = renderContext(data);
        })
        .catch(err => {
          slot.innerHTML = '<div style="color:var(--red);font-size:9px;margin-top:8px">context load failed: '+h(err.message)+'</div>';
        });
    });
  };

  window.clearAgentContextCache = function() { cache.clear(); };
})();
