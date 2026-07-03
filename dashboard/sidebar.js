// Sidebar — paginated run list
const SIDEBAR_PAGE_SIZE = 10;
let sidebarRuns = [];
let sidebarPage = 0;

async function sidebarRefresh() {
  try {
    const r = await fetch('/api/runs');
    sidebarRuns = await r.json();
    sidebarPage = 0;
    sidebarRender();
  } catch(e) {
    document.getElementById('sidebar-list').innerHTML =
      '<div style="color:var(--text-tertiary);padding:12px;font-size:12px">Failed to load runs</div>';
  }
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
    html += '<div class="sidebar-item' + (isActive ? ' active' : '') + '" onclick="sidebarSelect(\'' + r.run_id + '\')">' +
      '<span class="name">' + name.replace(/</g,'&lt;') + '</span>' +
      '<span class="id-mono">' + r.run_id.slice(0,8) + '</span>' +
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

// Auto-refresh sidebar on load
document.addEventListener('DOMContentLoaded', sidebarRefresh);
