// LLM input prompt inspector: formats the exact messages/request sent to LLMs.

(function() {
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

  function asArray(value) { return Array.isArray(value) ? value : []; }

  function compact(value, maxLen) {
    const text = pretty(value).replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLen ? text.slice(0, maxLen - 1) + '…' : text;
  }

  function pill(text, color) {
    if (!text && text !== 0) return '';
    return '<span style="display:inline-flex;align-items:center;padding:2px 6px;border:1px solid '+(color || 'var(--border-accent)')+';border-radius:999px;background:rgba(255,255,255,0.035);color:var(--text-secondary);font-size:8px;line-height:1.3;white-space:nowrap">'+h(text)+'</span>';
  }

  function card(title, meta, inner, accent) {
    return '<div style="border:1px solid '+(accent || 'rgba(255,255,255,0.08)')+';border-radius:7px;background:rgba(255,255,255,0.025);padding:7px;margin-top:6px;min-width:0">'+
      '<div style="display:flex;gap:6px;align-items:center;justify-content:space-between;min-width:0;margin-bottom:5px">'+
      '<div style="font-weight:700;color:var(--text-primary);font-size:10px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+h(title)+'</div>'+
      '<div style="color:var(--text-tertiary);font-size:8px;white-space:nowrap">'+h(meta || '')+'</div>'+
      '</div>'+inner+'</div>';
  }

  function rawDetails(title, value) {
    return '<details style="margin-top:6px;border-top:1px solid rgba(255,255,255,0.05);padding-top:5px">'+
      '<summary style="cursor:pointer;color:var(--text-tertiary);font-size:8px">raw '+h(title)+'</summary>'+
      '<pre style="white-space:pre-wrap;word-break:break-word;margin:5px 0 0;color:var(--text-tertiary);font-family:SFMono-Regular,monospace;font-size:8px;line-height:1.45;max-height:220px;overflow:auto">'+h(pretty(value))+'</pre>'+
      '</details>';
  }

  function copyButton(text) {
    const encoded = encodeURIComponent(text || '');
    return '<button type="button" onclick="navigator.clipboard&&navigator.clipboard.writeText(decodeURIComponent(\''+encoded.replace(/'/g, '%27')+'\'))" style="border:1px solid var(--border);background:rgba(255,255,255,0.04);color:var(--text-tertiary);border-radius:5px;font-size:8px;padding:2px 5px;cursor:pointer">copy</button>';
  }

  function promptBlock(text) {
    const value = text || '';
    return '<div style="display:flex;justify-content:flex-end;margin:-2px 0 4px">'+copyButton(value)+'</div>'+
      '<pre style="white-space:pre-wrap;word-break:break-word;margin:0;color:var(--text-secondary);font-family:SFMono-Regular,monospace;font-size:9px;line-height:1.45;max-height:260px;overflow:auto">'+h(value)+'</pre>';
  }

  function splitPromptSections(content) {
    const lines = String(content || '').split('\n');
    const sections = [];
    let current = null;
    lines.forEach(line => {
      if (/^#{1,3}\s+/.test(line)) {
        if (current) sections.push(current);
        current = {title: line.replace(/^#{1,3}\s+/, '').trim(), lines: []};
      } else if (current) {
        current.lines.push(line);
      } else if (line.trim()) {
        current = {title: 'Prompt', lines: [line]};
      }
    });
    if (current) sections.push(current);
    return sections;
  }

  function renderPromptSections(content) {
    const sections = splitPromptSections(content);
    if (!sections.length) return promptBlock(content || '');
    return sections.map(section => card(
      section.title,
      String(section.lines.join('\n')).length + ' chars',
      promptBlock(section.lines.join('\n').trim()),
      'rgba(88,166,255,0.18)'
    )).join('');
  }

  function roleColor(role) {
    if (role === 'system') return '#f778ba';
    if (role === 'user') return 'var(--accent)';
    if (role === 'tool') return '#2dd4bf';
    if (role === 'assistant') return '#a371f7';
    return 'var(--text-tertiary)';
  }

  function renderMessages(messages) {
    const rows = asArray(messages);
    if (!rows.length) {
      return '<div style="color:var(--yellow);font-size:9px;padding:5px 0">No captured LLM messages for this point.</div>';
    }
    return rows.map((m, idx) => {
      const role = m.role || 'message';
      const content = typeof m.content === 'string' ? m.content : pretty(m.content);
      const body = role === 'user' ? renderPromptSections(content) : promptBlock(content);
      return card(role + ' message', '#'+idx+' · '+content.length+' chars', body + rawDetails('message', m), roleColor(role));
    }).join('');
  }

  function renderList(title, values) {
    const items = asArray(values).filter(Boolean);
    const body = items.length ? '<div style="display:flex;gap:4px;flex-wrap:wrap">'+items.map(v => pill(v)).join('')+'</div>' : '<span style="color:var(--text-tertiary);font-size:9px">empty</span>';
    return '<div style="display:grid;grid-template-columns:78px minmax(0,1fr);gap:6px;padding:3px 0;border-top:1px solid rgba(255,255,255,0.045)">'+
      '<div style="color:var(--text-tertiary);font-size:8px;text-transform:uppercase;letter-spacing:.04em">'+h(title)+'</div><div>'+body+'</div></div>';
  }

  function renderMetadata(packet) {
    const meta = packet.agent_metadata || {};
    const html =
      renderList('skills', packet.skills || meta.skills)+
      renderList('toolsets', packet.toolsets || meta.toolsets)+
      renderList('read', packet.read_scope || meta.read_scope)+
      renderList('write', packet.write_scope || meta.write_scope)+
      '<div style="color:var(--text-secondary);font-size:9px;margin-top:5px;overflow-wrap:anywhere">'+
      '<b>role</b>: '+h(meta.role_id || packet.role_id || '')+' · '+
      '<b>profile</b>: '+h(meta.profile_name || '')+' · '+
      '<b>soul</b>: '+h(meta.soul || packet.soul || '')+'</div>';
    return card('Agent Metadata', '', html + rawDetails('agent metadata', meta), 'rgba(163,113,247,0.22)');
  }

  function renderTools(packet) {
    const flowTools = asArray(packet.available_tools);
    const html = renderList('flow tools', flowTools) +
      '<div style="color:var(--text-tertiary);font-size:8px;margin-top:5px">Flow tools are the tools exposed by this runtime packet. Runtime Trace tool schemas are shown here only if captured upstream.</div>';
    return card('Tools Available to LLM', flowTools.length + ' flow tools', html, 'rgba(45,212,191,0.22)');
  }

  function renderSummary(llmInput) {
    return '<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:5px 0 7px">'+
      pill(llmInput.source || 'unknown', 'rgba(88,166,255,.45)')+
      pill(llmInput.model || 'model missing')+
      pill(llmInput.provider || 'provider missing')+
      pill(llmInput.session_id ? 'session '+llmInput.session_id : '')+
      pill(llmInput.created_at || '')+
      '</div>';
  }

  window.renderLlmInputContext = function renderLlmInputContext(llmInput, fallbackPacket) {
    const packet = fallbackPacket || {};
    const input = llmInput || {
      source: 'missing', messages: packet.agent_prompt ? [{role:'user', content:packet.agent_prompt}] : [], request: {}, context_packet: packet,
    };
    let html = '<section style="margin-top:8px;border:1px solid rgba(247,120,186,0.35);border-radius:8px;padding:8px;background:linear-gradient(180deg,rgba(247,120,186,0.07),rgba(247,120,186,0.02))">';
    html += '<div style="font-weight:800;color:#f778ba;font-size:11px;letter-spacing:-.01em">LLM Input Context</div>';
    html += renderSummary(input);
    html += renderMessages(input.messages || []);
    html += renderMetadata(input.context_packet || packet);
    html += renderTools(input.context_packet || packet);
    html += rawDetails('request payload', input.request || {});
    html += '</section>';
    return html;
  };
})();
