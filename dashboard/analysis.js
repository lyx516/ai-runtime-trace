// Analysis tab — metric cards + agent activity + event timing
function renderAnalysis(panel, data) {
  if (!data.states || data.states.length === 0) {
    panel.innerHTML = '<div class="empty-state">No data to analyze</div>';
    return;
  }

  // Fetch thinking + decisions in parallel
  Promise.all([
    fetch('/api/runs/' + currentRunId + '/thinking').then(r => r.json().catch(()=>[])),
    fetch('/api/runs/' + currentRunId + '/decisions').then(r => r.json().catch(()=>[])),
  ]).then(([thinking, decisions]) => {
    const states = data.states;
    const edges = data.transitions || [];
    const current = data.current_state_id;

    // Metrics
    const totalDec = states.reduce((s, st) => s + (st.decisions ? st.decisions.length : 0), 0);
    const totalMsg = states.reduce((s, st) => s + (st.out_messages ? st.out_messages.length : 0) + (st.in_messages ? st.in_messages.length : 0), 0);
    const totalVisits = states.reduce((s, st) => s + (st.visit_count || 0), 0);
    const allRoles = new Set();
    states.forEach(s => (s.actors || []).forEach(a => allRoles.add(a)));
    const thinkEvents = Array.isArray(thinking) ? thinking : [];
    const decEvents = Array.isArray(decisions) ? decisions : [];

    let html = '';

    // Metric cards
    html += '<div class="metric-grid">';
    html += '<div class="metric-card"><div class="value">' + states.length + '</div><div class="label">States</div></div>';
    html += '<div class="metric-card"><div class="value">' + edges.length + '</div><div class="label">Transitions</div></div>';
    html += '<div class="metric-card"><div class="value">' + thinkEvents.length + '</div><div class="label">Thinking Events</div></div>';
    html += '<div class="metric-card"><div class="value">' + totalDec + '</div><div class="label">Decisions</div></div>';
    html += '<div class="metric-card"><div class="value">' + allRoles.size + '</div><div class="label">Agents</div></div>';
    html += '<div class="metric-card"><div class="value">' + totalMsg + '</div><div class="label">Messages</div></div>';
    html += '</div>';

    // Agent activity
    if (thinkEvents.length > 0 || decEvents.length > 0) {
      html += '<div class="section-title">Agent Activity</div>';
      const agentStats = {};
      thinkEvents.forEach(t => {
        const r = t.role_id || '?';
        if (!agentStats[r]) agentStats[r] = { thinking: 0, decisions: 0, approve: 0, changes: 0, reject: 0 };
        agentStats[r].thinking++;
      });
      decEvents.forEach(d => {
        const r = d.role_id || '?';
        if (!agentStats[r]) agentStats[r] = { thinking: 0, decisions: 0, approve: 0, changes: 0, reject: 0 };
        agentStats[r].decisions++;
        if (d.value === 'APPROVE') agentStats[r].approve++;
        else if (d.value === 'REQUEST_CHANGES') agentStats[r].changes++;
        else agentStats[r].reject++;
      });

      const maxThink = Math.max(1, ...Object.values(agentStats).map(v => v.thinking));
      html += '<div style="background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px">';
      Object.keys(agentStats).sort().forEach(r => {
        const s = agentStats[r];
        const pct = Math.round(s.thinking / maxThink * 100);
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">' +
          '<span style="font-size:11px;color:var(--text-secondary);width:80px;text-align:right;overflow:hidden;text-overflow:ellipsis">' + r + '</span>' +
          '<div style="flex:1;height:14px;background:var(--bg-base);border-radius:4px;overflow:hidden">' +
          '<div style="width:' + pct + '%;height:100%;background:var(--accent);border-radius:4px;transition:width .3s"></div></div>' +
          '<span style="font-size:11px;color:var(--text-secondary);min-width:50px">' + s.thinking + ' think</span>' +
          '<span style="font-size:11px">' +
          (s.approve > 0 ? '<span style="color:var(--green);margin-right:4px">' + s.approve + '✓</span>' : '') +
          (s.changes > 0 ? '<span style="color:var(--yellow);margin-right:4px">' + s.changes + '✗</span>' : '') +
          (s.reject > 0 ? '<span style="color:var(--red)">' + s.reject + '✗</span>' : '') +
          '</span></div>';
      });
      html += '</div>';
    }

    // Event type timing (from thinking events)
    if (thinkEvents.length > 0) {
      html += '<div class="section-title">Event Type Breakdown</div>';
      const typeCount = {};
      thinkEvents.forEach(t => {
        const st = t.step_type || 'unknown';
        if (!typeCount[st]) typeCount[st] = 0;
        typeCount[st]++;
      });
      const maxCount = Math.max(1, ...Object.values(typeCount));
      html += '<div style="background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px;font-size:12px">';
      Object.keys(typeCount).sort().forEach(st => {
        const c = typeCount[st];
        const pct = Math.round(c / maxCount * 100);
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">' +
          '<span style="color:var(--text-secondary);width:100px;overflow:hidden;text-overflow:ellipsis">' + st.replace(/_/g,' ') + '</span>' +
          '<div style="flex:1;height:12px;background:var(--bg-base);border-radius:4px;overflow:hidden">' +
          '<div style="width:' + pct + '%;height:100%;background:#a371f7;border-radius:4px"></div></div>' +
          '<span style="color:var(--text-tertiary)">' + c + 'x</span></div>';
      });
      html += '</div>';
    }

    // Decision distribution
    const decSum = {};
    states.forEach(s => (s.decisions || []).forEach(d => { decSum[d.value] = (decSum[d.value] || 0) + 1; }));
    if (Object.keys(decSum).length > 0) {
      html += '<div class="section-title">Decisions</div>';
      html += '<div class="dec-group">';
      Object.keys(decSum).sort().forEach(v => {
        const clr = v === 'APPROVE' || v === 'PASS' ? 'var(--green)' : v === 'REQUEST_CHANGES' ? 'var(--yellow)' : 'var(--red)';
        html += '<div class="dec-card"><div class="count" style="color:' + clr + '">' + decSum[v] + '</div><div class="lbl">' + v + '</div></div>';
      });
      html += '</div>';
    }

    // State table
    html += '<div class="section-title">States</div>';
    html += '<table class="data-table">';
    html += '<tr><th>State</th><th>Visits</th><th>Decisions</th><th>Messages</th></tr>';
    states.forEach(s => {
      html += '<tr' + (s.state_id === current ? ' class="current"' : '') + '>' +
        '<td style="font-weight:500">' + s.state_id + (s.state_id === current ? ' <span style="color:var(--accent);font-size:11px;font-weight:400">current</span>' : '') + '</td>' +
        '<td>' + (s.visit_count || 0) + '</td>' +
        '<td>' + (s.decisions ? s.decisions.length : 0) + '</td>' +
        '<td>' + ((s.out_messages? s.out_messages.length : 0) + (s.in_messages ? s.in_messages.length : 0)) + '</td></tr>';
    });
    html += '</table>';

    panel.innerHTML = html;
  }).catch(e => {
    panel.innerHTML = '<div class="empty-state">Error: ' + e.message + '</div>';
  });
}
