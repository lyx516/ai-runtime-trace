// Sidebar — paginated run list
const SIDEBAR_PAGE_SIZE = 10;
const SIDEBAR_TIME_ZONE = 'Asia/Shanghai';
let sidebarRuns = [];
let sidebarPage = 0;
let sidebarPollTimer = null;
let sidebarEventSource = null;
let sidebarRefreshTimer = null;
let sidebarRefreshInFlight = false;

function sidebarEscapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function formatRunTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts).slice(5, 16).replace('T', ' ');
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SIDEBAR_TIME_ZONE,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d).replace('/', '-');
}

function runSortKey(r) {
  const parsed = Date.parse(r.created_at || r.updated_at || '');
  return Number.isNaN(parsed) ? 0 : parsed;
}

function runChanged(prev, next) {
  if (!prev || !next) return false;
  return prev.updated_at !== next.updated_at ||
    prev.created_at !== next.created_at ||
    prev.db_size !== next.db_size ||
    prev.display_name !== next.display_name;
}

async function sidebarRefresh(options = {}) {
  if (sidebarRefreshInFlight) return;
  sidebarRefreshInFlight = true;
  const previousPage = sidebarPage;
  const previousById = new Map(sidebarRuns.map(r => [r.run_id, r]));
  try {
    const r = await fetch('/api/runs');
    sidebarRuns = await r.json();
    sidebarRuns.sort((a, b) => runSortKey(b) - runSortKey(a) || String(b.run_id || '').localeCompare(String(a.run_id || '')));
    const hasNewRun = sidebarRuns.some(run => !previousById.has(run.run_id));
    const currentRun = currentRunId ? sidebarRuns.find(run => run.run_id === currentRunId) : null;
    const currentRunChanged = currentRun ? runChanged(previousById.get(currentRunId), currentRun) : false;
    const totalPages = Math.max(1, Math.ceil(sidebarRuns.length / SIDEBAR_PAGE_SIZE));
    sidebarPage = hasNewRun ? 0 : options.preservePage ? Math.min(previousPage, totalPages - 1) : 0;
    sidebarRender();
    if (currentRunChanged && typeof requestCurrentRunRefresh === 'function') {
      requestCurrentRunRefresh({force: true});
    }
  } catch(e) {
    document.getElementById('sidebar-list').innerHTML =
      '<div style="color:var(--text-tertiary);padding:12px;font-size:12px">Failed to load runs</div>';
  } finally {
    sidebarRefreshInFlight = false;
  }
}

function scheduleSidebarRefresh(options = {}) {
  clearTimeout(sidebarRefreshTimer);
  sidebarRefreshTimer = setTimeout(() => sidebarRefresh(options), options.delay ?? 500);
}

function sidebarRender() {
  const list = document.getElementById('sidebar-list');
  const totalPages = Math.max(1, Math.ceil(sidebarRuns.length / SIDEBAR_PAGE_SIZE));
  const start = sidebarPage * SIDEBAR_PAGE_SIZE;
  const page = sidebarRuns.slice(start, start + SIDEBAR_PAGE_SIZE);

  let html = '';
  page.forEach(r => {
    const name = r.display_name || r.run_id.slice(0,12);
    const isActive = r.run_id === currentRunId;
    const timeLabel = formatRunTime(r.created_at || r.updated_at);
    html += '<div class="sidebar-item' + (isActive ? ' active' : '') + '" onclick="sidebarSelect(\'' + r.run_id + '\')">' +
      '<span class="name">' + sidebarEscapeHtml(name) + '</span>' +
      '<span title="UTC+8 created_at" style="font-size:9px;color:var(--text-tertiary);margin-left:auto;white-space:nowrap">' + sidebarEscapeHtml(timeLabel) + '</span>' +
      '<span class="id-mono">' + sidebarEscapeHtml(r.run_id.slice(0,8)) + '</span>' +
      '</div>';
  });
  list.innerHTML = html;

  document.getElementById('sidebar-page-info').textContent =
    (sidebarPage + 1) + '/' + totalPages + ' (' + sidebarRuns.length + ')';
  document.getElementById('sidebar-prev').disabled = sidebarPage <= 0;
  document.getElementById('sidebar-next').disabled = sidebarPage >= totalPages - 1;
}

function sidebarPrev() {
  if (sidebarPage > 0) { sidebarPage--; sidebarRender(); }
}

function sidebarNext() {
  const totalPages = Math.ceil(sidebarRuns.length / SIDEBAR_PAGE_SIZE);
  if (sidebarPage < totalPages - 1) { sidebarPage++; sidebarRender(); }
}

function sidebarSelect(runId) {
  document.getElementById('run-input').value = runId;
  loadRun();
  sidebarRender(); // highlight
}

function startSidebarLiveUpdates() {
  if (sidebarEventSource || sidebarPollTimer) return;
  if (window.EventSource) {
    sidebarEventSource = new EventSource('/api/events');
    sidebarEventSource.onmessage = e => {
      let payload = null;
      try { payload = JSON.parse(e.data); } catch (_) { return; }
      const runId = payload?.data?.run_id || payload?.run_id;
      scheduleSidebarRefresh({preservePage: true});
      if (runId && runId === currentRunId && typeof requestCurrentRunRefresh === 'function') {
        requestCurrentRunRefresh({force: true});
      }
    };
    sidebarEventSource.onerror = () => {
      // Keep the polling fallback active; browser will retry SSE automatically.
    };
  }
  sidebarPollTimer = setInterval(() => {
    scheduleSidebarRefresh({preservePage: true, delay: 0});
  }, 3000);
}

// Auto-refresh sidebar on load
document.addEventListener('DOMContentLoaded', () => {
  sidebarRefresh();
  startSidebarLiveUpdates();
});
