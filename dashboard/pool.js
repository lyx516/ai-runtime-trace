const state = {
  agents: [],
  skills: [],
  tools: [],
  selectedId: '',
  selected: null,
  pool: 'skills',
  dirty: false,
};

const $ = sel => document.querySelector(sel);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    throw new Error(data.error || `${res.status} ${res.statusText}`);
  }
  return data;
}

function setStatus(text, kind = '') {
  const pill = $('#status-pill');
  pill.textContent = text;
  pill.className = `status-pill ${kind}`.trim();
}

function toast(text, kind = '') {
  const el = $('#toast');
  el.textContent = text;
  el.className = `show ${kind}`.trim();
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { el.className = ''; }, 2600);
}

function setDirty(next = true) {
  state.dirty = next;
  const badge = $('#dirty-badge');
  if (badge) badge.textContent = next ? '未保存' : '';
  const save = $('#save-agent');
  if (save) save.disabled = !state.selected || !next;
}

function agentMatchesFilter(agent, q) {
  if (!q) return true;
  const haystack = [agent.id, agent.agent_id, agent.display_name, agent.role, agent.description, agent.relative_path].join(' ').toLowerCase();
  return haystack.includes(q);
}

function buildTreeHtml(parentId, childrenByParent, filteredIds) {
  const children = childrenByParent.get(parentId || '') || [];
  if (!children.length) return '';
  return children.map(agent => {
    const nested = buildTreeHtml(agent.id, childrenByParent, filteredIds);
    if (!filteredIds.has(agent.id) && !nested) return '';
    const hasKids = (childrenByParent.get(agent.id) || []).length > 0;
    const active = agent.id === state.selectedId ? ' active' : '';
    const kind = hasKids ? 'DIR' : 'AGT';
    return `
      <button class="tree-node${active}" type="button" data-agent-id="${escapeHtml(agent.id)}">
        <span class="node-kind">${kind}</span>
        <span class="node-title">
          <span class="node-name">${escapeHtml(agent.display_name || agent.id)}</span>
          <span class="node-meta">${escapeHtml(agent.id)}${agent.role ? ` · ${escapeHtml(agent.role)}` : ''}</span>
        </span>
      </button>
      ${nested ? `<div class="tree-group">${nested}</div>` : ''}
    `;
  }).join('');
}

function renderTree() {
  const q = ($('#agent-filter')?.value || '').trim().toLowerCase();
  const filteredIds = new Set(state.agents.filter(a => agentMatchesFilter(a, q)).map(a => a.id));
  const childrenByParent = new Map();
  const knownIds = new Set(state.agents.map(a => a.id));
  state.agents.forEach(agent => {
    const parent = agent.parent && knownIds.has(agent.parent) ? agent.parent : '';
    if (!childrenByParent.has(parent)) childrenByParent.set(parent, []);
    childrenByParent.get(parent).push(agent);
  });
  childrenByParent.forEach(list => list.sort((a, b) => String(a.display_name || a.id).localeCompare(String(b.display_name || b.id), 'zh-CN')));
  const html = buildTreeHtml('', childrenByParent, filteredIds);
  $('#agent-tree').innerHTML = html || '<div class="empty-note">没有匹配的 Agent</div>';
}

function tagHtml(value, kind, type) {
  const removable = kind === 'local';
  return `<span class="tag ${kind}">
    <span>${escapeHtml(value)}</span>
    ${removable ? `<button type="button" data-remove-${type}="${escapeHtml(value)}" aria-label="移除 ${escapeHtml(value)}">×</button>` : ''}
  </span>`;
}

function renderTagSection(title, type, inherited, local) {
  const inputId = `add-${type}-input`;
  const addLabel = type === 'skill' ? '添加 skill ID' : '添加 tool ID';
  const inheritedHtml = inherited.length ? inherited.map(v => tagHtml(v, 'inherited', type)).join('') : '<span class="empty-note">无继承项</span>';
  const localHtml = local.length ? local.map(v => tagHtml(v, 'local', type)).join('') : '<span class="empty-note">无本地项</span>';
  return `
    <section class="asset-section">
      <div class="asset-head">
        <h3>${title}</h3>
        <span class="asset-hint">继承只读，本地可编辑</span>
      </div>
      <div class="asset-hint">继承</div>
      <div class="tag-row">${inheritedHtml}</div>
      <div class="asset-hint" style="margin-top:10px">本地</div>
      <div class="tag-row">${localHtml}</div>
      <div class="add-inline">
        <input id="${inputId}" type="text" placeholder="${addLabel}">
        <button class="ghost-btn" type="button" data-add-${type}>添加</button>
      </div>
    </section>
  `;
}

function renderDetail() {
  const agent = state.selected;
  if (!agent) return;
  $('#detail').className = 'detail-wrap';
  $('#detail').innerHTML = `
    <div class="detail-header">
      <div>
        <h2>${escapeHtml(agent.display_name || agent.id)}</h2>
        <div class="detail-sub">${escapeHtml(agent.id)} · ${escapeHtml(agent.relative_path || '')}${agent.parent ? ` · parent ${escapeHtml(agent.parent)}` : ''}</div>
      </div>
      <div class="detail-actions">
        <span id="dirty-badge" class="dirty"></span>
        <button id="reload-agent" class="ghost-btn" type="button">重载</button>
        <button id="save-agent" class="primary-btn" type="button" disabled>保存</button>
      </div>
    </div>

    <div class="form-grid">
      <div class="field">
        <label for="edit-display-name">显示名</label>
        <input id="edit-display-name" type="text" value="${escapeHtml(agent.display_name || '')}">
      </div>
      <div class="field">
        <label for="edit-role">Role</label>
        <input id="edit-role" type="text" value="${escapeHtml(agent.role || '')}">
      </div>
      <div class="field">
        <label for="edit-description">描述</label>
        <input id="edit-description" type="text" value="${escapeHtml(agent.description || '')}">
      </div>
    </div>

    <div class="editor-grid">
      <div class="editor-block">
        <label for="edit-soul">本地 SOUL.md</label>
        <textarea id="edit-soul" spellcheck="false">${escapeHtml(agent.local_soul || '')}</textarea>
      </div>
      <div class="editor-block">
        <label>合并预览：父 soul + 本地 soul</label>
        <div class="preview-box">${escapeHtml(agent.soul || '')}</div>
      </div>
    </div>

    <div class="editor-block memory">
      <label for="edit-memory">Memory.md</label>
      <textarea id="edit-memory" spellcheck="false">${escapeHtml(agent.memory || '')}</textarea>
    </div>

    ${renderTagSection('Skills', 'skill', agent.inherited_skills || [], agent.local_skills || [])}
    ${renderTagSection('Tools', 'tool', agent.inherited_tools || [], agent.local_tools || [])}
  `;
  $('#detail').querySelectorAll('input, textarea').forEach(el => el.addEventListener('input', () => setDirty(true)));
  $('#reload-agent').addEventListener('click', () => selectAgent(agent.id, { force: true }));
  $('#save-agent').addEventListener('click', saveSelectedAgent);
  $('#detail').addEventListener('click', onDetailClick, { once: true });
}

function onDetailClick(event) {
  const removeSkill = event.target.closest('[data-remove-skill]')?.dataset.removeSkill;
  const removeTool = event.target.closest('[data-remove-tool]')?.dataset.removeTool;
  if (removeSkill) removeLocalValue('local_skills', removeSkill);
  if (removeTool) removeLocalValue('local_tools', removeTool);
  if (event.target.closest('[data-add-skill]')) addFromInput('skill');
  if (event.target.closest('[data-add-tool]')) addFromInput('tool');
  $('#detail')?.addEventListener('click', onDetailClick, { once: true });
}

function removeLocalValue(field, value) {
  state.selected[field] = (state.selected[field] || []).filter(v => v !== value);
  renderDetail();
  setDirty(true);
}

function addLocalValue(type, value) {
  if (!state.selected) {
    toast('先选择一个 Agent', 'err');
    return;
  }
  const field = type === 'skill' ? 'local_skills' : 'local_tools';
  const v = String(value || '').trim();
  if (!v) return;
  if (!state.selected[field].includes(v)) state.selected[field].push(v);
  renderDetail();
  setDirty(true);
}

function addFromInput(type) {
  const input = $(`#add-${type}-input`);
  addLocalValue(type, input?.value || '');
}

async function selectAgent(agentId, options = {}) {
  if (state.dirty && !options.force && !confirm('当前修改未保存，确定切换？')) return;
  state.selectedId = agentId;
  renderTree();
  $('#detail').className = 'detail-empty';
  $('#detail').innerHTML = '<div class="empty-title">加载中</div><p>读取 SOUL.md 和 meta.yaml...</p>';
  try {
    state.selected = await fetchJson(`/api/admin/agents/${encodeURIComponent(agentId)}`);
    history.replaceState(null, '', `#${encodeURIComponent(agentId)}`);
    state.dirty = false;
    renderDetail();
  } catch (err) {
    state.selected = null;
    $('#detail').innerHTML = `<div class="empty-title">读取失败</div><p>${escapeHtml(err.message)}</p>`;
    toast(err.message, 'err');
  }
}

async function saveSelectedAgent() {
  if (!state.selected) return;
  const payload = {
    display_name: $('#edit-display-name').value,
    role: $('#edit-role').value,
    description: $('#edit-description').value,
    local_soul: $('#edit-soul').value,
    memory: $('#edit-memory').value,
    local_skills: state.selected.local_skills || [],
    local_tools: state.selected.local_tools || [],
  };
  $('#save-agent').disabled = true;
  try {
    const result = await fetchJson(`/api/admin/agents/${encodeURIComponent(state.selected.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.selected = result.agent;
    await loadAgents({ keepSelection: true });
    renderDetail();
    setDirty(false);
    toast('已保存', 'ok');
  } catch (err) {
    $('#save-agent').disabled = false;
    toast(err.message, 'err');
  }
}

function poolMatches(item, q) {
  if (!q) return true;
  const haystack = [item.id, item.name, item.description, item.category, item.source].join(' ').toLowerCase();
  return haystack.includes(q);
}

function renderPool() {
  const q = ($('#pool-filter')?.value || '').trim().toLowerCase();
  const list = state.pool === 'skills' ? state.skills : state.tools;
  const type = state.pool === 'skills' ? 'skill' : 'tool';
  const filtered = list.filter(item => poolMatches(item, q));
  $(`#tab-skills`).classList.toggle('active', state.pool === 'skills');
  $(`#tab-tools`).classList.toggle('active', state.pool === 'tools');
  if (!filtered.length) {
    $('#pool-content').innerHTML = '<div class="empty-note">没有匹配项</div>';
    return;
  }
  $('#pool-content').innerHTML = filtered.map(item => `
    <article class="pool-item">
      <div class="pool-item-top">
        <div class="pool-item-title">
          <strong>${escapeHtml(item.name || item.id)}</strong>
          <code>${escapeHtml(item.id)}</code>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span class="source-pill">${escapeHtml(item.source || item.category || 'tool')}</span>
          <button class="ghost-btn" type="button" data-pool-add="${type}" data-pool-id="${escapeHtml(item.id)}">添加</button>
        </div>
      </div>
      ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ''}
      <div class="mini-code">${escapeHtml(item.relative_path || '')}</div>
    </article>
  `).join('');
}

async function loadAgents(options = {}) {
  const data = await fetchJson('/api/admin/agents');
  state.agents = data.agents || [];
  $('#agent-root').textContent = data.root ? data.root : 'agents/';
  renderTree();
  if (options.keepSelection && state.selectedId) return;
  const hashId = decodeURIComponent(location.hash.slice(1) || '');
  const first = state.agents.find(a => a.id === hashId) || state.agents[0];
  if (first) await selectAgent(first.id, { force: true });
}

async function loadPools() {
  const [skills, tools] = await Promise.all([
    fetchJson('/api/admin/skills'),
    fetchJson('/api/admin/tools'),
  ]);
  state.skills = skills.skills || [];
  state.tools = tools.tools || [];
  renderPool();
}

async function refreshAll(options = {}) {
  setStatus('连接中');
  try {
    await Promise.all([loadAgents(options), loadPools()]);
    setStatus('已连接', 'ok');
  } catch (err) {
    setStatus('错误', 'err');
    toast(err.message, 'err');
  }
}

$('#agent-tree').addEventListener('click', event => {
  const btn = event.target.closest('[data-agent-id]');
  if (btn) selectAgent(btn.dataset.agentId);
});
$('#agent-filter').addEventListener('input', renderTree);
$('#pool-filter').addEventListener('input', renderPool);
$('#refresh-btn').addEventListener('click', () => refreshAll({ keepSelection: true }));
$('.segmented').addEventListener('click', event => {
  const btn = event.target.closest('[data-pool]');
  if (!btn) return;
  state.pool = btn.dataset.pool;
  renderPool();
});
$('#pool-content').addEventListener('click', event => {
  const btn = event.target.closest('[data-pool-add]');
  if (!btn) return;
  addLocalValue(btn.dataset.poolAdd, btn.dataset.poolId);
});

document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
    event.preventDefault();
    if (state.dirty) saveSelectedAgent();
  }
});

refreshAll();
