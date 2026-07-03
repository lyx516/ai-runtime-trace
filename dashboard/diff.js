// Diff tab - side-by-side comparison of two runs
function renderDiff(panel) {
  panel.innerHTML = `
    <div style="display:flex;gap:10px;margin-bottom:14px;align-items:center">
      <input id="diff-a" type="text" placeholder="Run ID A" style="flex:1;background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px;color:var(--text-primary);font-family:SFMono-Regular,'SF Mono',monospace;font-size:13px">
      <input id="diff-b" type="text" placeholder="Run ID B" style="flex:1;background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 10px;color:var(--text-primary);font-family:SFMono-Regular,'SF Mono',monospace;font-size:13px">
      <button onclick="runDiff()" style="padding:6px 14px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--bg-surface);color:var(--text-primary);cursor:pointer">Compare</button>
    </div>
    <div id="diff-result" style="font-family:SFMono-Regular,'SF Mono',monospace;font-size:12px"></div>
  `;
}

async function runDiff() {
  const a = document.getElementById('diff-a').value.trim();
  const b = document.getElementById('diff-b').value.trim();
  const div = document.getElementById('diff-result');
  if (!a || !b) { div.textContent = 'Enter two Run IDs'; return; }
  div.innerHTML = '<div style="color:var(--text-tertiary)">Loading ...</div>';

  try {
    const [rA, rB] = await Promise.all([
      fetch('/api/runs/' + a + '/graph').then(r => r.json()),
      fetch('/api/runs/' + b + '/graph').then(r => r.json()),
    ]);
    if (rA.error || rB.error) { div.textContent = rA.error || rB.error; return; }

    let html = '<div class="diff-grid">';
    html += diffCol(a, rA, '#58a6ff');
    html += diffCol(b, rB, '#3fb950');
    html += '</div>';

    // State comparison table
    const ids = new Set([...(rA.states||[]).map(s=>s.state_id), ...(rB.states||[]).map(s=>s.state_id)]);
    html += '<div class="section-title" style="margin-top:16px">State differences</div>';
    html += '<table class="data-table"><tr><th>State</th><th>A visits</th><th>B visits</th><th>A dec</th><th>B dec</th><th>Delta</th></tr>';
    ids.forEach(sid => {
      const sa = (rA.states||[]).find(s => s.state_id === sid);
      const sb = (rB.states||[]).find(s => s.state_id === sid);
      const vA = sa ? (sa.visit_count || 0) : 0;
      const vB = sb ? (sb.visit_count || 0) : 0;
      const dA = sa ? (sa.decisions ? sa.decisions.length : 0) : 0;
      const dB = sb ? (sb.decisions ? sb.decisions.length : 0) : 0;
      if (vA !== vB || dA !== dB) {
        const sV = vB - vA >= 0 ? '+' : '';
        const sD = dB - dA >= 0 ? '+' : '';
        html += '<tr><td>' + sid + '</td><td>' + vA + '</td><td>' + vB + '</td><td>' + dA + '</td><td>' + dB + '</td><td style="color:var(--yellow)">v:' + sV + (vB-vA) + ' d:' + sD + (dB-dA) + '</td></tr>';
      }
    });
    html += '</table>';
    div.innerHTML = html;
  } catch(e) { div.innerHTML = '<div style="color:var(--red)">' + e.message + '</div>'; }
}

function diffCol(id, data, color) {
  const st = data.states || [];
  const totalDec = st.reduce((s, st) => s + (st.decisions ? st.decisions.length : 0), 0);
  const totalMsg = st.reduce((s, st) => s + (st.out_messages ? st.out_messages.length : 0), 0);
  return '<div class="diff-col" style="border-left:3px solid ' + color + '">' +
    '<h3 style="color:' + color + '">' + id.slice(0,12) + '</h3>' +
    '<div style="font-size:12px;color:var(--text-secondary);line-height:1.8">' +
    'Status: ' + (data.status||'?') + '<br>' +
    'Current: ' + (data.current_state_id||'?') + '<br>' +
    'States: ' + st.length + '<br>' +
    'Transitions: ' + (data.transitions||[]).length + '<br>' +
    'Decisions: ' + totalDec + '<br>' +
    'Messages: ' + totalMsg +
    '</div></div>';
}
