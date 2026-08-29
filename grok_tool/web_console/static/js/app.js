import * as api from './api.js?v=1.61';
import { toast } from './toast.js?v=1.59';

const getTools = api.getTools;
const getToolStats = api.getToolStats;
const getToolResults = api.getToolResults;
const getCurrentJob = api.getCurrentJob;
const startJob = api.startJob;
const stopJob = api.stopJob;
const getConfigSummary = api.getConfigSummary;
const getHealth = api.getHealth;
const getHotmails =
  typeof api.getHotmails === 'function'
    ? api.getHotmails
    : async () => ({ count: 0, accounts: [], slots: 0 });
const importHotmails =
  typeof api.importHotmails === 'function'
    ? api.importHotmails
    : async () => {
        throw new Error('API Hotmail chưa sẵn sàng — restart web server');
      };
const getSolverStatus = api.getSolverStatus;
const solverAction = api.solverAction;
const getDashboard =
  typeof api.getDashboard === 'function' ? api.getDashboard : async () => ({});
const getHealthAccounts =
  typeof api.getHealthAccounts === 'function'
    ? api.getHealthAccounts
    : async () => ({ accounts: [] });
const runHealthCheck =
  typeof api.runHealthCheck === 'function'
    ? api.runHealthCheck
    : async () => {
        throw new Error('API health-check chưa sẵn sàng — restart web server');
      };
const rerunJob =
  typeof api.rerunJob === 'function'
    ? api.rerunJob
    : async () => {
        throw new Error('API re-run chưa sẵn sàng — restart web server');
      };
const getBackups =
  typeof api.getBackups === 'function' ? api.getBackups : async () => ({});
const runBackup =
  typeof api.runBackup === 'function'
    ? api.runBackup
    : async () => {
        throw new Error('API backup chưa sẵn sàng — restart web server');
      };
const getProxies =
  typeof api.getProxies === 'function'
    ? api.getProxies
    : async () => ({ enabled: false, mode: 'rotate', proxies: [], count: 0 });
const saveProxies =
  typeof api.saveProxies === 'function'
    ? api.saveProxies
    : async () => {
        throw new Error('API Proxy chưa sẵn sàng — restart web server');
      };

const PAGE_META = {
  '#/register': { title: 'Đăng ký', eyebrow: 'Control Plane' },
  '#/dashboard': { title: 'Dashboard', eyebrow: 'Thống kê & sức khỏe acc' },
  '#/history': { title: 'Lịch sử Job', eyebrow: 'Runs & Re-run' },
  '#/results': { title: 'Kết quả', eyebrow: 'Accounts & Status' },
  '#/logs': { title: 'Logs', eyebrow: 'Live Stream' },
  '#/proxy': { title: 'Proxy', eyebrow: 'Pool dùng chung mọi tool' },
  '#/settings': { title: 'Cài đặt', eyebrow: 'System Config' },
  '#/tools': { title: 'Tools', eyebrow: 'Plugin Registry' },
};

// Số dòng tối đa giữ trong DOM của log-box (log đầy đủ vẫn nằm ở state.jobLogs)
const MAX_DOM_LINES = 1000;

const state = {
  tools: [],
  selectedTool: 'grok',
  form: {},
  job: null,
  queue: [],
  solver: null,
  es: null,
  logSeq: 0,
  jobId: null,
  jobLogs: [],
  poolCache: {},
  statsCache: null,
  routeToken: 0,
  pollTimer: null,
  autoScroll: true,
  hotmailDraft: '',
  hotmailPool: null,
  resultsFilter: { q: '', st: 'all' },
};

function isHotmailMail(val) {
  const v = String(val ?? '').trim().toLowerCase();
  return v === '1' || v === 'hotmail' || v === 'outlook' || v === 'ms';
}

const SHEET_ONLY = ['heygen', 'capcut', 'zai', 'canva', 'netflix', 'manus', 'notion', 'genspark'];
const HAS_HOTMAIL = ['grok', ...SHEET_ONLY.filter((id) => id !== 'notion')];

function isSheetOnly(id) {
  return SHEET_ONLY.includes(id);
}

function hasHotmailPool(id) {
  return HAS_HOTMAIL.includes(id);
}

function brandIconSrc(t) {
  const src = t.brand_icon || `/static/img/brands/${t.id}.svg`;
  if (!src) return src;
  return src.includes('?') ? src : `${src}?v=1.61`;
}

function brandIconHtml(t) {
  const src = brandIconSrc(t);
  const name = t.name || t.id || '';
  return `<div class="ico brand-official" data-brand="${esc(t.id)}">
    <img src="${esc(src)}" alt="${esc(name)}" width="40" height="40"
      onerror="this.onerror=null;this.remove();this.parentElement.classList.add('is-fallback');" />
    <span class="ico-fallback">${esc(t.icon || '')}</span>
  </div>`;
}

/* ── Theme / chrome ── */
function initChrome() {
  const btn = document.getElementById('theme-toggle');
  btn?.addEventListener('click', () => {
    const dark = document.documentElement.classList.toggle('dark-theme');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  });

  const menu = document.getElementById('mobile-menu');
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('sidebar-scrim');
  const close = () => {
    sidebar?.classList.remove('is-open');
    scrim?.classList.remove('is-open');
  };
  menu?.addEventListener('click', () => {
    sidebar?.classList.toggle('is-open');
    scrim?.classList.toggle('is-open');
  });
  scrim?.addEventListener('click', close);
  document.querySelectorAll('.nav-item').forEach((a) => {
    a.addEventListener('click', close);
  });
}

function setActiveNav(hash) {
  document.querySelectorAll('.nav-item').forEach((a) => {
    a.classList.toggle('is-active', a.dataset.route === hash);
  });
  const meta = PAGE_META[hash] || PAGE_META['#/register'];
  const t = document.getElementById('page-title');
  const e = document.getElementById('page-eyebrow');
  if (t) t.textContent = meta.title;
  if (e) e.textContent = meta.eyebrow;
  document.title = `${meta.title} · Draco Reg`;
}

function revealLiveLog() {
  const panel = document.querySelector('.console-card') || document.getElementById('log-box');
  if (!panel) return;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  panel.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  const box = document.getElementById('log-box');
  if (box) box.scrollTop = box.scrollHeight;
}

function updateRunPill(job) {
  const pill = document.getElementById('run-pill');
  const text = document.getElementById('run-pill-text');
  if (!pill || !text) return;
  const running = job && ['running', 'pending', 'stopping'].includes(job.status);
  pill.classList.toggle('is-running', !!running);
  const qn = (state.queue || []).length;
  if (!job || job.status === 'idle') text.textContent = qn ? `Idle · queue ${qn}` : 'Idle';
  else text.textContent = `${job.tool_id || 'job'} · ${job.status}${qn ? ` · Q${qn}` : ''}`;
}

/* ── Solver pill ── */
async function refreshSolverPill() {
  try {
    const s = await getSolverStatus();
    state.solver = s;
    paintSolverPill(s);
    paintSolverCard(s);
  } catch (_) {
    /* solver API offline — giữ nguyên pill */
  }
}

function paintSolverPill(s) {
  const pill = document.getElementById('solver-pill');
  const text = document.getElementById('solver-pill-text');
  if (!pill || !text) return;
  const online = !!s?.online;
  pill.classList.toggle('is-online', online);
  text.textContent = online ? `Solver :${s.port || '5072'}` : 'Solver offline';
}

function paintSolverCard(s) {
  const line = document.getElementById('solver-status-line');
  if (!line || !s) return;
  line.innerHTML = s.online
    ? `<span class="tag tag-ok">online</span>`
    : `<span class="tag tag-fail">offline</span>`;
  const url = document.getElementById('solver-url');
  if (url) url.textContent = s.url || 'http://127.0.0.1:5072';
  const pid = document.getElementById('solver-pid');
  if (pid) pid.textContent = s.managed ? String(s.pid ?? '—') : 'không phải process của console';
  const lastErr = document.getElementById('solver-last-error');
  if (lastErr) {
    lastErr.textContent = s.last_error || '';
    lastErr.hidden = !s.last_error;
  }
}

/* ── Helpers ── */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function lineClass(line) {
  const l = line.toLowerCase();
  if (/error|fail|fatal|❌/.test(l)) return 'err';
  if (/success|✅|ok |done/.test(l)) return 'ok';
  if (/warn|⚠/.test(l)) return 'warn';
  if (/info|▶|===|sub2api|sso/.test(l)) return 'info';
  return '';
}

function statusTag(status, ok) {
  if (ok) return `<span class="tag tag-ok">${esc(status || 'ok')}</span>`;
  if (/pending|manual|stopped/i.test(status || '')) {
    return `<span class="tag tag-mid">${esc(status)}</span>`;
  }
  return `<span class="tag tag-fail">${esc(status || 'fail')}</span>`;
}

function toolLabel() {
  const t = (state.tools || []).find((x) => x.id === state.selectedTool);
  return t?.name || 'tool';
}

function hotmailPlanText(pool) {
  const acc = Number(pool?.count ?? 0);
  const slots = Number(pool?.slots ?? acc);
  const maxA = Number(pool?.max_aliases ?? 5);
  const name = toolLabel();
  if (!acc) return 'Pool trống — import Hotmail rồi Start.';
  if (maxA <= 1) {
    return `Sẽ reg <strong>${slots}</strong> acc ${esc(name)} từ ${acc} Hotmail (1 mail = 1 acc).`;
  }
  return `Sẽ reg <strong>${slots}</strong> acc ${esc(name)} từ ${acc} Hotmail (mỗi acc tối đa ${maxA} alias).`;
}

function syncHotmailUi(root) {
  const hotmail = isHotmailMail(state.form.mail);
  const panel = root.querySelector('#hotmail-pool');
  const countWrap = root.querySelector('[data-field-wrap="count"]');
  const plan = root.querySelector('#hotmail-plan');
  if (panel) panel.hidden = !hotmail;
  if (countWrap) countWrap.hidden = hotmail;
  if (plan) {
    plan.hidden = !hotmail;
    plan.innerHTML = hotmailPlanText(state.hotmailPool);
  }
}

function syncCustomDomainUi(root) {
  const isCustom = String(state.form.mail ?? '') === '5';
  const wrap = root.querySelector('[data-field-wrap="custom_domain"]');
  if (wrap) wrap.hidden = !isCustom;
  const wrapRead = root.querySelector('[data-field-wrap="custom_read_mailbox"]');
  if (wrapRead) wrapRead.hidden = !isCustom;
}

function syncCanvaJobUi(root) {
  if (state.selectedTool !== 'canva') return;
  const redeem = String(state.form.job || 'reg') === 'redeem';
  const codesEl = root.querySelector('[data-field-wrap="codes"]');
  if (codesEl) codesEl.hidden = false;
  const thr = root.querySelector('[data-field-wrap="threads"]');
  if (thr) thr.hidden = false; // threads dùng cả reg (Chrome song song) lẫn redeem
  const panel = root.querySelector('#hotmail-pool');
  const plan = root.querySelector('#hotmail-plan');
  if (redeem) {
    if (panel) panel.hidden = true;
    if (plan) plan.hidden = true;
    const countWrap = root.querySelector('[data-field-wrap="count"]');
    if (countWrap) countWrap.hidden = true;
  }
}

function hotmailPanelHtml(pool, show) {
  return `
    <div class="hotmail-panel" id="hotmail-pool" ${show ? '' : 'hidden'}>
      <div class="card-head" style="margin-bottom:10px">
        <div>
          <div class="card-title">Pool Hotmail</div>
          <div class="card-sub" id="hotmail-pool-count">${hotmailCountHtml(pool)}</div>
        </div>
      </div>
      <div class="field">
        <label>Dán Hotmail vào đây</label>
        <textarea id="hotmail-draft" rows="7" placeholder="email|password|refresh_token|client_id
email:password
email----password----client_id----refresh_token">${esc(state.hotmailDraft || '')}</textarea>
        <div class="hint">1 dòng = 1 acc. Nhận <span class="mono">|</span> <span class="mono">:</span> <span class="mono">----</span> <span class="mono">;</span> tab.${(pool?.max_aliases ?? 5) > 1 ? ` Alias +1…+${(pool?.max_aliases ?? 5) - 1} dùng ở lần Start sau (còn slot).` : ''}</div>
      </div>
      <div class="btn-row" style="margin:8px 0 12px">
        <button type="button" class="btn btn-ghost" id="btn-hotmail-browse">Browse file</button>
        <button type="button" class="btn btn-primary" id="btn-hotmail-add">Thêm vào pool</button>
        <button type="button" class="btn btn-ghost" id="btn-hotmail-replace">Ghi đè pool</button>
        <input type="file" id="hotmail-file" accept=".txt,.csv,.tsv,.log,.text,text/plain" hidden />
      </div>
      <div class="hotmail-list-wrap">
        <div class="card-sub" style="margin-bottom:6px">Đang trong pool</div>
        <div id="hotmail-list">${hotmailListHtml(pool)}</div>
      </div>
    </div>
  `;
}

function bindHotmailPanel(root, toolId) {
  const panel = root.querySelector('#hotmail-pool');
  const draft = root.querySelector('#hotmail-draft');
  const fileEl = root.querySelector('#hotmail-file');
  if (!panel) return;

  const syncDraft = () => {
    if (draft) state.hotmailDraft = draft.value;
  };
  draft?.addEventListener('input', syncDraft);

  const applyPool = (pool) => {
    state.hotmailPool = pool;
    state.poolCache[toolId] = pool;
    const next = hotmailPanelHtml(pool, true);
    panel.insertAdjacentHTML('afterend', next);
    panel.remove();
    bindHotmailPanel(root, toolId);
    const mailSel = root.querySelector('[data-key="mail"]');
    if (mailSel) state.form.mail = mailSel.value;
    syncHotmailUi(root);
  };

  const send = async (mode) => {
    syncDraft();
    const text = (state.hotmailDraft || '').trim();
    if (!text) {
      toast('Dán Hotmail hoặc Browse file trước', 'err');
      return;
    }
    if (mode === 'replace' && !confirm('Ghi đè toàn bộ data/hotmails.txt?')) return;
    try {
      const res = await importHotmails(toolId, text, mode);
      state.hotmailDraft = '';
      const added = res.added ?? 0;
      const skipped = res.skipped ?? 0;
      const invalid = res.invalid ?? 0;
      toast(
        mode === 'replace'
          ? `Đã ghi đè ${res.count ?? 0} acc`
          : `Thêm ${added} · bỏ trùng ${skipped}${invalid ? ` · lỗi ${invalid}` : ''}`,
        invalid && !added ? 'err' : 'ok'
      );
      applyPool(res);
    } catch (err) {
      toast(err.message || String(err), 'err');
    }
  };

  root.querySelector('#btn-hotmail-browse')?.addEventListener('click', () => fileEl?.click());
  fileEl?.addEventListener('change', async () => {
    const file = fileEl.files && fileEl.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      state.hotmailDraft = text;
      if (draft) draft.value = text;
      toast(`Đã đọc ${file.name} (${text.split(/\r?\n/).filter((l) => l.trim()).length} dòng)`, 'ok');
    } catch (err) {
      toast(err.message || 'Không đọc được file', 'err');
    }
    fileEl.value = '';
  });
  root.querySelector('#btn-hotmail-add')?.addEventListener('click', () => send('append'));
  root.querySelector('#btn-hotmail-replace')?.addEventListener('click', () => send('replace'));
}

/* ── Pages ── */
function swapIn(el) {
  if (!el) return;
  el.classList.remove('swap-in');
  void el.offsetWidth; // ép reflow để animation chạy lại mỗi lần swap
  el.classList.add('swap-in');
}

function jobStatusText() {
  const job = state.job;
  if (!job) return 'Chưa có job';
  const qn = (state.queue || []).length;
  return `${esc(job.tool_id || '')} · ${esc(job.status || '')}${job.id ? ' · ' + esc(job.id) : ''}${qn ? ` · queue ${qn}` : ''}`;
}

/* 4 stat-card + (blurb tách riêng bên ngoài để không vỡ grid) */
function statsGridHtml(tool, stats) {
  return `
    <div class="stat-card info" title="Số email khác nhau (lấy status lần cuối)">
      <div class="stat-label">Email (unique)</div>
      <div class="stat-value">${stats.unique_emails ?? stats.total ?? '—'}</div>
      <div class="card-sub" style="margin-top:4px">${stats.attempts ?? '—'} lượt thử</div>
    </div>
    <div class="stat-card ok" title="${isSheetOnly(tool.id) ? 'Reg thành công — chỉ lên Google Sheet, không Sub2' : 'Reg xong: Sub2API + reg-only + reg OK nhưng sub2 fail'}">
      <div class="stat-label">Reg OK</div>
      <div class="stat-value">${stats.success ?? '—'}</div>
      <div class="card-sub" style="margin-top:4px">${isSheetOnly(tool.id) ? `lên sheet ${esc(tool.id)}, không Sub2` : `chỉ reg: ${stats.reg_only ?? 0} · sub2 fail: ${stats.sub2_fail ?? 0}`}</div>
    </div>
    ${isSheetOnly(tool.id) ? `
    <div class="stat-card" title="${esc(tool.name)} không import Sub2API">
      <div class="stat-label">Google Sheet</div>
      <div class="stat-value">${stats.success ?? '—'}</div>
      <div class="card-sub" style="margin-top:4px">tab ${esc(tool.id)}</div>
    </div>` : `
    <div class="stat-card" title="Đã import Sub2API (added_sub2api)">
      <div class="stat-label">Sub2API OK</div>
      <div class="stat-value">${stats.sub2api ?? '—'}</div>
      <div class="card-sub" style="margin-top:4px">trong ${stats.success ?? 0} reg OK</div>
    </div>`}
    <div class="stat-card bad" title="error* lần status cuối mỗi email">
      <div class="stat-label">Fail</div>
      <div class="stat-value">${stats.fail ?? '—'}</div>
      <div class="card-sub" style="margin-top:4px">pending: ${stats.pending ?? 0}</div>
    </div>
  `;
}

function toolFieldsHtml(tool) {
  return (tool.fields || [])
    .map((f) => {
      if (f.type === 'select') {
        return `<div class="field" data-field-wrap="${esc(f.key)}">
          <label>${esc(f.label)}</label>
          <select data-key="${esc(f.key)}">
            ${(f.options || [])
              .map(
                (o) =>
                  `<option value="${esc(o.value)}" ${String(state.form[f.key]) === String(o.value) ? 'selected' : ''}>${esc(o.label)}${o.hint ? ' — ' + esc(o.hint) : ''}</option>`
              )
              .join('')}
          </select>
          ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}
        </div>`;
      }
      if (f.type === 'checkbox') {
        const checked = state.form[f.key] === true || state.form[f.key] === 'true' || state.form[f.key] === 1;
        return `<div class="check-row" data-field-wrap="${esc(f.key)}">
          <input type="checkbox" data-key="${esc(f.key)}" id="f-${esc(f.key)}" ${checked ? 'checked' : ''} />
          <label for="f-${esc(f.key)}" style="margin:0;color:var(--text-primary)">${esc(f.label)}</label>
        </div>
        ${f.hint ? `<div class="hint" style="margin-top:-6px">${esc(f.hint)}</div>` : ''}`;
      }
      if (f.type === 'textarea') {
        return `<div class="field span-2 redeem-box" data-field-wrap="${esc(f.key)}">
          <label>${esc(f.label)}</label>
          <textarea data-key="${esc(f.key)}" rows="5" placeholder="CANVASPIDERMAN
MOI_MA_KHAC">${esc(state.form[f.key] ?? f.default ?? '')}</textarea>
          ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}
        </div>`;
      }
      return `<div class="field" data-field-wrap="${esc(f.key)}" ${f.key === 'count' && isHotmailMail(state.form.mail) ? 'hidden' : ''}>
        <label>${esc(f.label)}</label>
        <input type="${f.type === 'number' ? 'number' : 'text'}" data-key="${esc(f.key)}"
          value="${esc(state.form[f.key] ?? f.default)}"
          ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''} />
        ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}
      </div>`;
    })
    .join('');
}

function hotmailListHtml(pool) {
  const acc = pool?.accounts || [];
  const rows = acc
    .slice(0, 40)
    .map(
      (a) => `<li>
        <span class="mono">${esc(a.email)}</span>
        <span class="hm-flags">
          ${a.has_refresh ? '<span class="tag tag-ok">refresh</span>' : '<span class="tag tag-mid">no token</span>'}
          ${a.has_client_id ? '<span class="tag tag-ok">cid</span>' : ''}
        </span>
      </li>`
    )
    .join('');
  return acc.length
    ? `<ul class="hotmail-list">${rows}${acc.length > 40 ? `<li class="card-sub">… +${acc.length - 40} acc nữa</li>` : ''}</ul>`
    : `<div class="empty" style="padding:16px">Pool trống — dán list hoặc Browse từ Explorer.</div>`;
}

function hotmailCountHtml(pool) {
  const acc = pool?.accounts || [];
  const count = pool?.count ?? acc.length;
  const maxA = pool?.max_aliases ?? 5;
  return `${count} Hotmail · Start sẽ reg ${pool?.slots ?? count} ${esc(toolLabel())}${maxA > 1 ? ` (×${maxA} alias)` : ''} · <span class="mono">${esc(pool?.path || 'data/hotmails.txt')}</span>`;
}

function hotmailPlanHtml(pool) {
  return `<div class="hotmail-plan" id="hotmail-plan" ${isHotmailMail(state.form.mail) ? '' : 'hidden'}>${hotmailPlanText(pool)}</div>`;
}

function actionRowHtml(tool, running) {
  return `
    ${tool.external_url ? `<a class="btn btn-primary" href="${esc(tool.external_url)}" target="_blank" rel="noopener" title="Mở web GPT-TOOL đầy đủ trong tab mới">Mở GPT-TOOL ↗</a>` : ''}
    <button class="btn btn-primary" id="btn-start" data-locked="${tool.status !== 'ready' ? '1' : '0'}" ${tool.status !== 'ready' ? 'disabled' : ''}>Start${running ? ' (xếp hàng)' : ''}</button>
    ${tool.id === 'canva' ? `<button class="btn btn-ghost" id="btn-start-redeem" ${tool.status !== 'ready' ? 'disabled' : ''}>Start redeem</button>` : ''}
    <button class="btn btn-danger" id="btn-stop" ${!running ? 'disabled' : ''}>Stop</button>
    <button class="btn btn-ghost" id="btn-refresh-stats">Stats</button>
  `;
}

function nextNameHtml(tool, stats) {
  if (isSheetOnly(tool.id) || !stats?.next_name) return '';
  return `Next Sub2API name: <span class="mono">${esc(stats.next_name)}</span> · Hotmail pool: ${stats.hotmails ?? 0}`;
}

function registerPageHtml(tool, stats, running) {
  const nl = nextNameHtml(tool, stats);
  return `
    <div class="page">
      <div id="stats-grid" class="grid-4">${statsGridHtml(tool, stats)}</div>
      <div id="stats-blurb" class="card-sub" style="margin-top:-6px">${stats.blurb ? esc(stats.blurb) : ''}</div>

      <div class="workspace">
        <div class="card">
          <div class="card-head">
            <div>
              <div class="card-title">Cấu hình</div>
              <div class="card-sub">Chọn tool, mail, số lượng. Stop ghi data/STOP.</div>
            </div>
          </div>

          <div class="tool-grid" style="margin-bottom:16px">
            ${state.tools
              .map((t) => {
                const soon = t.status === 'coming_soon';
                const sel = t.id === tool.id;
                return `<button type="button" class="tool-tile ${sel ? 'is-selected' : ''} ${soon ? 'is-soon' : ''}" data-tool="${esc(t.id)}" ${soon ? 'disabled' : ''}>
                  ${brandIconHtml(t)}
                  <strong>${esc(t.name)}</strong>
                  <p>${esc(t.description)}</p>
                  <span class="badge ${soon ? 'badge-soon' : 'badge-ready'}" style="margin-top:8px">${soon ? 'Soon' : 'Ready'}</span>
                </button>`;
              })
              .join('')}
          </div>

          <div class="form-stack form-grid" id="tool-form">
            ${toolFieldsHtml(tool)}
          </div>

          <div id="form-aux">
            ${hasHotmailPool(tool.id) ? hotmailPanelHtml(state.hotmailPool, isHotmailMail(state.form.mail)) : ''}
            ${hasHotmailPool(tool.id) ? hotmailPlanHtml(state.hotmailPool) : ''}
          </div>

          <div id="next-name-line" class="card-sub" style="margin-top:12px" ${nl ? '' : 'hidden'}>${nl}</div>

          <div class="btn-row action-row" id="action-row">
            ${actionRowHtml(tool, running)}
          </div>
        </div>

        <div class="card console-card">
          <div class="log-head">
            <div style="display:flex;align-items:center;gap:10px;min-width:0">
              <span class="term-dots" aria-hidden="true"><i></i><i></i><i></i></span>
              <div>
                <div class="card-title">Live log</div>
                <div class="card-sub" id="job-status-line">${jobStatusText()}</div>
              </div>
            </div>
            <div class="log-actions">
              <label class="check-row" style="padding:6px 10px;margin:0">
                <input type="checkbox" id="auto-scroll" ${state.autoScroll ? 'checked' : ''} />
                <span style="font-size:12px">Auto-scroll</span>
              </label>
              <button class="btn btn-ghost" id="btn-copy-log" type="button">Copy log</button>
            </div>
          </div>
          <div class="log-console" id="log-box"></div>
        </div>
      </div>

      <div class="card" style="margin-top:18px">
        <div class="card-head">
          <div>
            <div class="card-title">Xem mail tmail</div>
            <div class="card-sub">Dán địa chỉ tmail (kể cả hộp cũ) — hiện mail + mã OTP luôn, khỏi vào tmail.wibucrypto.pro.</div>
          </div>
        </div>
        <div class="btn-row" style="gap:8px">
          <input type="text" id="mail-lookup-input" placeholder="m0r8y6l77x@bizon.name.ng" style="flex:1" />
          <button class="btn btn-ghost" id="btn-mail-lookup" type="button">Đọc hộp thư</button>
        </div>
        <div id="mail-lookup-result" hidden></div>
      </div>
    </div>
  `;
}

function bindToolForm(root, tool) {
  root.querySelectorAll('[data-key]').forEach((el) => {
    const key = el.dataset.key;
    const sync = () => {
      if (el.type === 'checkbox') state.form[key] = el.checked;
      else if (el.type === 'number') state.form[key] = el.value === '' ? 0 : Number(el.value);
      else state.form[key] = el.value;
      if (key === 'mail') syncHotmailUi(root);
      if (key === 'mail') syncCustomDomainUi(root);
      if (key === 'job') syncCanvaJobUi(root);
    };
    el.addEventListener('change', sync);
    el.addEventListener('input', sync);
  });
  bindHotmailPanel(root, tool.id);
  syncHotmailUi(root);
  syncCustomDomainUi(root);
  syncCanvaJobUi(root);
}

async function onStart(ev) {
  const root = document.getElementById('main-content');
  const btn = ev.currentTarget;
  try {
    // collect form
    root.querySelectorAll('[data-key]').forEach((el) => {
      const key = el.dataset.key;
      if (el.type === 'checkbox') state.form[key] = el.checked;
      else if (el.type === 'number') {
        const raw = String(el.value ?? '').trim();
        const n = Number(raw);
        state.form[key] = raw === '' || Number.isNaN(n) ? Number(el.min || 1) : n;
      } else state.form[key] = el.value;
    });
    if (state.form.job === 'redeem') {
      const raw = String(state.form.codes || '').trim();
      if (!raw) {
        toast('Dán mã redeem vào ô Mã redeem (mỗi dòng 1 mã)', 'err');
        return;
      }
    } else if (isHotmailMail(state.form.mail)) {
      try {
        state.hotmailPool = await getHotmails(state.selectedTool);
      } catch (_) {}
      const n = Number(state.hotmailPool?.slots || state.hotmailPool?.count || 0);
      if (!n) {
        toast('Pool Hotmail trống / hết slot — import acc rồi Start', 'err');
        return;
      }
      syncHotmailUi(root);
    }
    const runningNow = state.job && ['running', 'pending', 'stopping'].includes(state.job.status);
    if (runningNow && !confirm('Job đang chạy — xếp job mới vào hàng đợi?')) return;

    btn.disabled = true;
    const oldLabel = btn.textContent;
    btn.textContent = 'Đang start…';
    try {
      const res = await startJob(state.selectedTool, { ...state.form });
      state.logSeq = 0;
      state.jobId = null;
      state.jobLogs = [];
      state.job = res.job;
      state.statsCache = null;
      toast(res.job?.status === 'queued' ? 'Đã xếp vào hàng đợi' : 'Đã Start job', 'ok');
      applyJobSnapshot(res.job);
      const tool = (state.tools || []).find((t) => t.id === state.selectedTool);
      if (tool) loadRegisterData(root, tool);
      revealLiveLog();
    } finally {
      btn.disabled = false;
      btn.textContent = oldLabel;
    }
  } catch (err) {
    toast(err.message || String(err), 'err');
  }
}

function bindActionRow(root) {
  document.getElementById('btn-start')?.addEventListener('click', onStart);
  document.getElementById('btn-stop')?.addEventListener('click', async () => {
    try {
      const res = await stopJob(state.job?.id || null);
      toast(res.message || 'Đang dừng…', 'ok');
      revealLiveLog();
    } catch (err) {
      toast(err.message || String(err), 'err');
    }
  });
  document.getElementById('btn-refresh-stats')?.addEventListener('click', async () => {
    const tool = (state.tools || []).find((t) => t.id === state.selectedTool);
    if (tool) loadRegisterData(root, tool);
    toast('Đã refresh stats', 'ok');
    revealLiveLog();
  });
  document.getElementById('btn-start-redeem')?.addEventListener('click', () => {
    const sel = root.querySelector('[data-key="job"]');
    if (sel) sel.value = 'redeem';
    state.form.job = 'redeem';
    document.getElementById('btn-start')?.click();
  });
}

function bindRegisterPage(root, tool) {
  const liveBox = document.getElementById('log-box');
  bindLogBox(liveBox);
  paintLogs(liveBox, state.jobLogs || []);

  const mailInput = root.querySelector('#mail-lookup-input');
  const mailBtn = root.querySelector('#btn-mail-lookup');
  const mailOut = root.querySelector('#mail-lookup-result');
  const runMailLookup = async () => {
    const addr = (mailInput.value || '').trim();
    if (!addr.includes('@') || !addr.includes('.')) {
      toast('Nhập địa chỉ dạng ten@domain', 'err');
      return;
    }
    mailBtn.disabled = true;
    const oldLabel = mailBtn.textContent;
    mailBtn.textContent = 'Đang đọc…';
    mailOut.hidden = false;
    mailOut.innerHTML = '<div class="hint">Đang lấy thư từ tmail… (vài giây)</div>';
    try {
      const data = await api.lookupMail(addr);
      const msgs = data.messages || [];
      mailOut.innerHTML = msgs.length
        ? msgs
            .map(
              (m) => `
          <div class="mail-row">
            <div class="mail-row-top">
              <span class="mail-subj">${esc(m.subject)}</span>
              ${
                m.codes && m.codes.length
                  ? `<span class="mail-code" title="Bấm để copy">${esc(m.codes[0])}</span>`
                  : ''
              }
            </div>
            ${m.preview ? `<div class="hint">${esc(m.preview)}</div>` : ''}
          </div>`
            )
            .join('')
        : '<div class="hint">Hộp trống — chưa có mail nào.</div>';
    } catch (e) {
      mailOut.innerHTML = `<div class="hint" style="color:#e5484d">Lỗi: ${esc(String(e.message || e))}</div>`;
    } finally {
      mailBtn.disabled = false;
      mailBtn.textContent = oldLabel;
    }
  };
  if (mailBtn && mailInput && mailOut) {
    mailBtn.addEventListener('click', runMailLookup);
    mailInput.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') runMailLookup();
    });
    mailOut.addEventListener('click', async (ev) => {
      const chip = ev.target.closest('.mail-code');
      if (!chip) return;
      try {
        await navigator.clipboard.writeText(chip.textContent.trim());
        toast('Đã copy mã ' + chip.textContent.trim(), 'ok');
      } catch (_) {
        toast('Không copy được — chọn tay', 'err');
      }
    });
  }

  root.querySelectorAll('[data-tool]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const t = (state.tools || []).find((x) => x.id === btn.dataset.tool);
      // Tool có web riêng (GPT-TOOL :8083) → chọn tile là nhảy sang luôn.
      // window.open phải chạy trước mọi await để không bị popup blocker chặn.
      if (t && t.external_url) {
        const w = window.open(t.external_url, '_blank', 'noopener');
        fetch(t.external_url, { mode: 'no-cors', cache: 'no-store' }).catch(() => {
          try { if (w) w.close(); } catch (_) {}
          toast('GPT-TOOL :8083 chưa chạy — bấm Start ở tool GPT / OpenAI để bật service', 'err');
        });
      }
      const next = btn.dataset.tool;
      if (next === state.selectedTool) return;
      // phản hồi tức thì trên lưới tile, không chờ fetch
      root.querySelectorAll('.tool-tile').forEach((b) => {
        b.classList.toggle('is-selected', b.dataset.tool === next);
      });
      state.selectedTool = next;
      state.form = {};
      switchTool(root, t || state.tools.find((x) => x.id === next));
    });
  });

  bindToolForm(root, tool);
  bindActionRow(root);

  document.getElementById('auto-scroll')?.addEventListener('change', (e) => {
    setAutoScroll(e.target.checked, { scrollBox: document.getElementById('log-box') });
  });
  document.getElementById('btn-copy-log')?.addEventListener('click', async () => {
    try {
      await copyLogBox(document.getElementById('log-box'));
    } catch {
      toast('Copy thất bại', 'err');
    }
  });
}

function switchTool(root, tool) {
  // defaults into form
  for (const f of tool.fields || []) {
    if (state.form[f.key] === undefined) state.form[f.key] = f.default;
  }
  state.hotmailPool = state.poolCache[tool.id] || { count: 0, accounts: [] };
  // "Hotmail đọc OTP": bơm danh sách acc trong pool vào select (mail domain
  // riêng forward về 1 acc cố định — user chọn đúng acc đó).
  const readField = (tool.fields || []).find((f) => f.key === 'custom_read_mailbox');
  if (readField) {
    const accs = (state.hotmailPool?.accounts || []).map((a) => a.email);
    readField.options = [
      { value: 'auto', label: 'Tự động — đầu pool', hint: 'mặc định' },
      ...accs.map((e) => ({ value: e, label: e, hint: '' })),
    ];
  }
  const stats = state.statsCache && state.statsCache.tool === tool.id ? state.statsCache.stats : {};
  const running = state.job && ['running', 'pending', 'stopping'].includes(state.job.status);

  const formEl = root.querySelector('#tool-form');
  const gridEl = root.querySelector('#stats-grid');
  const blurbEl = root.querySelector('#stats-blurb');
  const auxEl = root.querySelector('#form-aux');
  const actionEl = root.querySelector('#action-row');
  const nextEl = root.querySelector('#next-name-line');
  if (formEl) formEl.innerHTML = toolFieldsHtml(tool);
  if (gridEl) gridEl.innerHTML = statsGridHtml(tool, stats);
  if (blurbEl) blurbEl.innerHTML = stats.blurb ? esc(stats.blurb) : '';
  if (auxEl) {
    auxEl.innerHTML = hasHotmailPool(tool.id)
      ? hotmailPanelHtml(state.hotmailPool, isHotmailMail(state.form.mail)) + hotmailPlanHtml(state.hotmailPool)
      : '';
  }
  if (actionEl) actionEl.innerHTML = actionRowHtml(tool, running);
  if (nextEl) {
    const nl = nextNameHtml(tool, stats);
    nextEl.innerHTML = nl;
    nextEl.hidden = !nl;
  }
  swapIn(formEl);
  swapIn(auxEl);
  swapIn(actionEl);

  bindToolForm(root, tool);
  bindActionRow(root);
  loadRegisterData(root, tool);
}

async function loadRegisterData(root, tool) {
  const id = tool.id;
  const token = state.routeToken;
  const needPool = hasHotmailPool(id) || (tool.fields || []).some((f) => f.key === 'custom_read_mailbox');
  const [stats, pool] = await Promise.all([
    tool.status === 'ready' ? getToolStats(id).catch(() => ({})) : Promise.resolve({}),
    needPool ? getHotmails(id).catch(() => null) : Promise.resolve(null),
  ]);
  // người dùng đã chuyển tool / sang trang khác trong lúc fetch — bỏ qua
  if (token !== state.routeToken || state.selectedTool !== id) return;

  state.statsCache = { tool: id, stats };
  if (pool) {
    state.hotmailPool = pool;
    state.poolCache[id] = pool;
  }

  const grid = root.querySelector('#stats-grid');
  if (grid) grid.innerHTML = statsGridHtml(tool, stats);
  const blurbEl = root.querySelector('#stats-blurb');
  if (blurbEl) blurbEl.innerHTML = stats.blurb ? esc(stats.blurb) : '';
  const nextEl = root.querySelector('#next-name-line');
  if (nextEl) {
    const nl = nextNameHtml(tool, stats);
    nextEl.innerHTML = nl;
    nextEl.hidden = !nl;
  }
  if (grid) swapIn(grid);

  if (pool) {
    const listEl = root.querySelector('#hotmail-list');
    if (listEl) listEl.innerHTML = hotmailListHtml(pool);
    const countEl = root.querySelector('#hotmail-pool-count');
    if (countEl) countEl.innerHTML = hotmailCountHtml(pool);
    const planEl = root.querySelector('#hotmail-plan');
    if (planEl && isHotmailMail(state.form.mail)) planEl.innerHTML = hotmailPlanText(pool);
    const readField = (tool.fields || []).find((f) => f.key === 'custom_read_mailbox');
    if (readField) {
      const accs = (pool.accounts || []).map((a) => a.email);
      readField.options = [
        { value: 'auto', label: 'Tự động — đầu pool', hint: 'mặc định' },
        ...accs.map((e) => ({ value: e, label: e, hint: '' })),
      ];
      const sel = root.querySelector('[data-key="custom_read_mailbox"]');
      if (sel) {
        const cur = sel.value || state.form.custom_read_mailbox || 'auto';
        sel.innerHTML = readField.options
          .map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`)
          .join('');
        if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
        else {
          sel.value = 'auto';
          state.form.custom_read_mailbox = 'auto';
        }
      }
    }
  }
}

async function renderRegister(root) {
  if (!state.tools.length) {
    const data = await getTools();
    state.tools = data.tools || [];
  }
  let tool = state.tools.find((t) => t.id === state.selectedTool) || state.tools[0];
  if (!tool) {
    root.innerHTML = `<div class="empty">Không có tool</div>`;
    return;
  }
  state.selectedTool = tool.id;

  // defaults into form
  for (const f of tool.fields || []) {
    if (state.form[f.key] === undefined) state.form[f.key] = f.default;
  }
  state.hotmailPool = state.poolCache[tool.id] || state.hotmailPool || { count: 0, accounts: [] };
  // "Hotmail đọc OTP": bơm danh sách acc trong pool vào select (mail domain
  // riêng forward về 1 acc cố định — user chọn đúng acc đó).
  const readField = (tool.fields || []).find((f) => f.key === 'custom_read_mailbox');
  if (readField) {
    const accs = (state.hotmailPool?.accounts || []).map((a) => a.email);
    readField.options = [
      { value: 'auto', label: 'Tự động — đầu pool', hint: 'mặc định' },
      ...accs.map((e) => ({ value: e, label: e, hint: '' })),
    ];
  }

  // render ngay với cache — không chờ mạng; stats/hotmail patch sau khi có
  const stats = state.statsCache && state.statsCache.tool === tool.id ? state.statsCache.stats : {};
  const running = state.job && ['running', 'pending', 'stopping'].includes(state.job.status);

  root.innerHTML = registerPageHtml(tool, stats, running);
  bindRegisterPage(root, tool);
  loadRegisterData(root, tool);
}

/* Paint log gom theo frame (rAF): khi SSE đẩy log dày đặc, nhiều bản tin
   trong cùng 1 frame chỉ tốn đúng 1 lần reflow — hết cảnh giật trang khi
   vừa cuộn vừa có log đổ về. */
let logPaintPending = false;
function scheduleLogPaint(box) {
  if (!box || logPaintPending) return;
  logPaintPending = true;
  requestAnimationFrame(() => {
    logPaintPending = false;
    paintLogs(box, state.jobLogs || []);
  });
}

function selectionIn(el) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return false;
  const node = sel.anchorNode;
  return !!(node && el.contains(node));
}

function makeLogLine(text) {
  const div = document.createElement('div');
  div.className = `line ${lineClass(text)}`;
  div.textContent = text;
  return div;
}

function logBoxText(box) {
  if (!box) return '';
  return [...box.querySelectorAll('.line')].map((el) => el.textContent).join('\n');
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch (_) {
    /* fall through */
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  ta.remove();
}

function isLogAtBottom(box, slop = 48) {
  if (!box) return true;
  return box.scrollHeight - box.scrollTop - box.clientHeight < slop;
}

function setAutoScroll(on, { scrollBox } = {}) {
  state.autoScroll = !!on;
  const cb = document.getElementById('auto-scroll');
  if (cb && cb.checked !== state.autoScroll) cb.checked = state.autoScroll;
  if (state.autoScroll && scrollBox) scrollBox.scrollTop = scrollBox.scrollHeight;
}

function paintLogs(box, lines) {
  if (!box) return;
  const next = Array.isArray(lines) ? lines : [];
  const selecting = selectionIn(box);
  // Keep streaming while the user is selecting/copying. Only skip a full
  // rewrite — that would wipe the highlight and look like the log "stopped".
  const pin =
    !selecting &&
    !box.dataset.holdScroll &&
    (state.autoScroll || isLogAtBottom(box));

  // box chỉ giữ MAX_DOM_LINES dòng cuối; offset = số dòng đã cắt khỏi DOM
  // (vẫn nằm trong `next`). Khi `next` ngắn hơn cửa sổ DOM → job mới/reset.
  let offset = Number(box.dataset.trimOffset || 0);
  const kids = box.children;
  const prevN = kids.length;
  if (next.length < offset + prevN) {
    offset = 0;
    box.dataset.trimOffset = '0';
  }

  const canAppend =
    prevN > 0 &&
    next.length >= offset + prevN &&
    kids[0].textContent === next[offset] &&
    kids[prevN - 1].textContent === next[offset + prevN - 1];

  if (canAppend) {
    if (next.length === offset + prevN) return;
    const frag = document.createDocumentFragment();
    for (let i = offset + prevN; i < next.length; i++) frag.appendChild(makeLogLine(next[i]));
    box.appendChild(frag);
    const over = box.children.length - MAX_DOM_LINES;
    if (over > 0) {
      for (let i = 0; i < over; i++) box.removeChild(box.firstChild);
      box.dataset.trimOffset = String(offset + over);
    }
  } else {
    if (selecting) return;
    const startIdx = Math.max(offset, next.length - MAX_DOM_LINES);
    const frag = document.createDocumentFragment();
    for (let i = startIdx; i < next.length; i++) frag.appendChild(makeLogLine(next[i]));
    box.replaceChildren(frag);
    box.dataset.trimOffset = String(startIdx);
  }
  if (pin) box.scrollTop = box.scrollHeight;
}

function bindLogBox(box) {
  if (!box || box.dataset.copyBound) return;
  box.dataset.copyBound = '1';
  box.setAttribute('tabindex', '0');
  box.setAttribute('role', 'log');
  box.setAttribute('aria-label', 'Live log — bôi chọn để copy');
  box.addEventListener('keydown', (e) => {
    const key = String(e.key).toLowerCase();
    if (!(e.ctrlKey || e.metaKey)) return;
    if (key === 'a') {
      e.preventDefault();
      e.stopPropagation();
      const range = document.createRange();
      range.selectNodeContents(box);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
    if (key === 'c') {
      // Copy only — never treat Ctrl+C in the log as Stop.
      e.stopPropagation();
      const sel = window.getSelection();
      const picked =
        sel && !sel.isCollapsed && box.contains(sel.anchorNode)
          ? sel.toString()
          : '';
      if (picked) return;
      e.preventDefault();
      copyLogBox(box).catch(() => toast('Copy thất bại', 'err'));
    }
  });
  box.addEventListener('copy', (e) => {
    e.stopPropagation();
  });
  box.addEventListener('pointerdown', (e) => {
    box.dataset.holdScroll = '1';
    try {
      box.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
  });
  const release = () => {
    delete box.dataset.holdScroll;
    setAutoScroll(isLogAtBottom(box));
  };
  box.addEventListener('pointerup', release);
  box.addEventListener('pointercancel', release);
  // wheel + scroll dùng chung 1 rAF: tránh đọc scrollHeight (forced layout)
  // nhiều lần trong cùng 1 frame khi đang cuộn log
  let scrollSyncRaf = 0;
  const syncAutoScroll = () => {
    if (scrollSyncRaf) return;
    scrollSyncRaf = requestAnimationFrame(() => {
      scrollSyncRaf = 0;
      setAutoScroll(isLogAtBottom(box));
    });
  };
  box.addEventListener('wheel', syncAutoScroll, { passive: true });
  box.addEventListener('scroll', syncAutoScroll, { passive: true });
}

async function copyLogBox(box) {
  const text = logBoxText(box);
  await copyToClipboard(text);
  const n = text ? text.split('\n').length : 0;
  toast(n ? `Đã copy ${n} dòng log` : 'Log trống', n ? 'ok' : 'err');
}

function filterRows(rows) {
  const { q, st } = state.resultsFilter;
  const needle = String(q || '').trim().toLowerCase();
  return rows.filter((r) => {
    if (st === 'ok' && !r.ok) return false;
    if (st === 'fail' && (r.ok || /pending|manual/i.test(r.status || ''))) return false;
    if (st === 'pending' && !/pending|manual/i.test(r.status || '')) return false;
    if (!needle) return true;
    const hay = `${r.email || ''} ${r.status || ''} ${r.extra || r.offer || r.plan || ''}`.toLowerCase();
    return hay.includes(needle);
  });
}

function rowsToCsv(rows) {
  const escCell = (v) => {
    const s = String(v ?? '');
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = 'email,password,status,extra';
  const body = rows
    .map((r) =>
      [r.email, r.password, r.status, r.extra || r.offer || r.plan || '']
        .map(escCell)
        .join(',')
    )
    .join('\n');
  return `${head}\n${body}\n`;
}

function downloadCsv(rows, name) {
  const blob = new Blob(['\ufeff' + rowsToCsv(rows)], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/* ── Dashboard: biểu đồ SVG thuần + health acc ── */
function barChartSvg(labels, values, { width = 640, height = 160 } = {}) {
  const max = Math.max(1, ...values);
  const n = labels.length || 1;
  const pad = { l: 8, r: 8, t: 10, b: 18 };
  const iw = width - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const bw = Math.max(4, (iw / n) * 0.62);
  const step = iw / n;
  let bars = '';
  for (let i = 0; i < n; i++) {
    const h = Math.round((values[i] / max) * ih);
    const x = pad.l + i * step + (step - bw) / 2;
    const y = pad.t + ih - h;
    bars += `<rect x="${x}" y="${y}" width="${bw.toFixed(1)}" height="${h}" rx="2"
      class="chart-bar"><title>${esc(labels[i])}: ${values[i]}</title></rect>`;
    if (n <= 16 || i % Math.ceil(n / 12) === 0) {
      bars += `<text x="${(pad.l + i * step + step / 2).toFixed(1)}" y="${height - 4}"
        text-anchor="middle" class="chart-label">${esc(labels[i])}</text>`;
    }
  }
  return `<svg viewBox="0 0 ${width} ${height}" class="chart" role="img" aria-label="Jobs theo ngày">
    <line x1="${pad.l}" y1="${pad.t + ih}" x2="${width - pad.r}" y2="${pad.t + ih}" class="chart-axis"/>
    ${bars}
  </svg>`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('vi-VN', { hour12: false });
}

function fmtBytes(n) {
  const v = Number(n || 0);
  if (v >= 1048576) return `${(v / 1048576).toFixed(1)} MB`;
  if (v >= 1024) return `${(v / 1024).toFixed(1)} KB`;
  return `${v} B`;
}

function todayKeyLocal() {
  const d = new Date();
  const p = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

async function renderDashboard(root) {
  root.innerHTML = `<div class="empty">Loading…</div>`;
  const [dash, health, bk] = await Promise.all([
    getDashboard(14).catch(() => null),
    getHealthAccounts().catch(() => ({ accounts: [] })),
    getBackups().catch(() => null),
  ]);
  if (!dash) {
    root.innerHTML = `<div class="empty">API dashboard chưa sẵn sàng — restart web server</div>`;
    return;
  }
  const lg = dash.ledger || {};
  const js = dash.jobs || {};
  const stMap = dash.job_status || {};
  const toolRuns = Object.entries(dash.tool_runs || {});
  const alivePct = health.total
    ? Math.round((health.alive / Math.max(1, health.alive + health.dead)) * 100)
    : null;

  root.innerHTML = `
    <div class="page">
      <div class="grid-4">
        <div class="stat-card ok"><div class="stat-label">Reg OK</div><div class="stat-value">${lg.ok ?? 0}</div>
          <div class="card-sub">tỷ lệ OK ${lg.success_rate ?? 0}% trên ${(lg.ok ?? 0) + (lg.fail ?? 0)} lượt có kết quả</div></div>
        <div class="stat-card bad"><div class="stat-label">Fail</div><div class="stat-value">${lg.fail ?? 0}</div>
          <div class="card-sub">pending ${lg.pending ?? 0} · tổng ${lg.total ?? 0} dòng ledger</div></div>
        <div class="stat-card info"><div class="stat-label">Job đã chạy</div><div class="stat-value">${js.total ?? 0}</div>
          <div class="card-sub">TB ${js.avg_duration_sec ?? 0}s/job · done ${stMap.done ?? 0} · error ${stMap.error ?? 0}</div></div>
        <div class="stat-card ${alivePct != null && alivePct < 80 ? 'bad' : ''}">
          <div class="stat-label">Acc Sub2API sống</div>
          <div class="stat-value">${health.configured === false ? '—' : (alivePct != null ? `${alivePct}%` : '…')}</div>
          <div class="card-sub">${health.checked_at ? `check lúc ${fmtTime(health.checked_at)} · ${health.alive}/${health.total}` : 'chưa check — bấm bên dưới'}</div></div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head"><div><div class="card-title">Job chạy theo ngày</div>
            <div class="card-sub">14 ngày gần nhất (nguồn data/jobs.jsonl)</div></div></div>
          ${barChartSvg(dash.labels || [], dash.jobs_per_day || [])}
        </div>
        <div class="card">
          <div class="card-head"><div><div class="card-title">Lượt chạy theo tool</div>
            <div class="card-sub">toàn bộ lịch sử job</div></div></div>
          ${toolRuns.length
            ? `<ul class="bar-list">${toolRuns.map(([id, n]) => `
                <li><span class="mono">${esc(id)}</span>
                  <span class="bar-track"><i style="width:${Math.round((n / Math.max(...toolRuns.map(([, m]) => m))) * 100)}%"></i></span>
                  <b>${n}</b></li>`).join('')}</ul>`
            : '<div class="empty">Chưa có job nào</div>'}
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Sức khỏe acc Sub2API</div>
            <div class="card-sub">Kiểm tra định kỳ nền (mặc định 6h/lần, config: health_check.interval_hours). Acc chuyển sống→chết sẽ báo Telegram/webhook.</div>
          </div>
          <button class="btn btn-primary" id="btn-health-run">Check ngay</button>
        </div>
        <div id="health-body">${
          health.accounts?.length
            ? `<div class="table-wrap" style="max-height:320px"><table class="results">
                <thead><tr><th>Tên acc</th><th>Trạng thái</th><th>Mã</th><th>Ghi chú</th></tr></thead>
                <tbody>${health.accounts.map((a) => `
                  <tr>
                    <td class="mono">${esc(a.name)}</td>
                    <td>${a.verdict === 'alive'
                      ? '<span class="tag tag-ok">ALIVE</span>'
                      : a.verdict === 'dead'
                        ? '<span class="tag tag-fail">DEAD</span>'
                        : '<span class="tag tag-mid">unknown</span>'}</td>
                    <td class="mono">${a.code || '—'}</td>
                    <td class="mono">${esc(a.reason || '')}</td>
                  </tr>`).join('')}</tbody></table></div>`
            : `<div class="empty">Chưa có dữ liệu check. Cần cấu hình sub2api trong config.json rồi bấm "Check ngay".</div>`
        }</div>
      </div>

      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Backup tự động</div>
            <div class="card-sub">Giữ ${bk?.keep_days ?? 14} ngày · lưu tại ${esc(bk?.dir || 'data/backups')} — ${bk?.today_backed_up ? 'hôm nay đã backup ✅' : 'chưa có backup hôm nay'}</div>
          </div>
          <button class="btn btn-ghost" id="btn-backup-run">Backup ngay</button>
        </div>
        ${(bk?.backups || []).length
          ? `<div class="table-wrap" style="max-height:240px"><table class="results">
              <thead><tr><th>Ngày</th><th>File</th><th>Dung lượng</th><th></th></tr></thead>
              <tbody>${bk.backups.map((b) => `
                <tr>
                  <td class="mono">${esc(b.date)}</td>
                  <td class="mono">${b.files?.length ?? 0} file</td>
                  <td class="mono">${fmtBytes(b.bytes)}</td>
                  <td>${b.date === todayKeyLocal() ? '<span class="tag tag-ok">hôm nay</span>' : ''}</td>
                </tr>`).join('')}</tbody></table></div>`
          : `<div class="empty">Chưa có bản backup nào — bấm "Backup ngay" hoặc đợi web boot.</div>`}
      </div>
    </div>
  `;

  document.getElementById('btn-backup-run')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = 'Đang backup…';
    try {
      const r = await runBackup();
      if (r.skipped) toast(`Hôm nay đã có backup (${r.date}) — bỏ qua`, 'ok');
      else toast(`Đã copy ${r.copied?.length ?? 0} file vào ${r.date}${r.missing?.length ? ` · thiếu ${r.missing.length}` : ''}`, 'ok');
      await renderDashboard(root);
    } catch (e) {
      toast(e.message || String(e), 'err');
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  });

  document.getElementById('btn-health-run')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = 'Đang check…';
    try {
      const r = await runHealthCheck();
      if (!r.configured) toast(r.message || 'Sub2API chưa cấu hình', 'err');
      else toast(`Check xong: ${r.alive} sống · ${r.dead} chết · ${r.unknown} unknown`, r.dead ? 'err' : 'ok');
      await renderDashboard(root);
    } catch (e) {
      toast(e.message || String(e), 'err');
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  });
}

/* ── History: danh sách job + re-run ── */
const JOB_TAG = {
  done: ['tag-ok', 'DONE'],
  error: ['tag-fail', 'ERROR'],
  stopped: ['tag-mid', 'STOPPED'],
  running: ['tag-ok', 'RUNNING'],
  pending: ['tag-mid', 'PENDING'],
  queued: ['tag-mid', 'QUEUED'],
  stopping: ['tag-mid', 'STOPPING'],
};

function jobTag(status) {
  const [cls, label] = JOB_TAG[status] || ['tag-mid', status || '?'];
  return `<span class="tag ${cls}">${esc(label)}</span>`;
}

async function renderHistory(root) {
  root.innerHTML = `<div class="empty">Loading…</div>`;
  let jobs = [];
  try {
    const r = await api.listJobs();
    jobs = r.jobs || [];
  } catch (e) {
    root.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }

  root.innerHTML = `
    <div class="page">
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Lịch sử job (${jobs.length})</div>
            <div class="card-sub">20 job gần nhất · params đã redact · log đầy đủ ở data/logs/<job_id>.log</div>
          </div>
          <button class="btn btn-ghost" id="btn-history-refresh">Refresh</button>
        </div>
        ${
          jobs.length
            ? `<div class="table-wrap"><table class="results">
                <thead><tr><th>Thời điểm</th><th>Tool</th><th>Trạng thái</th><th>Params</th><th>Exit</th><th></th></tr></thead>
                <tbody>${jobs.map((j) => `
                  <tr>
                    <td class="mono">${fmtTime(j.created_at)}</td>
                    <td class="mono">${esc(j.tool_id)}</td>
                    <td>${jobTag(j.status)}</td>
                    <td class="mono hist-params" title='${esc(JSON.stringify(j.params || {}))}'>${esc(
                      Object.entries(j.params || {})
                        .map(([k, v]) => `${k}=${typeof v === 'boolean' ? (v ? 'on' : 'off') : v}`)
                        .join(' ')
                        .slice(0, 90)
                    )}</td>
                    <td class="mono">${j.exit_code ?? '—'}</td>
                    <td><button class="btn btn-ghost btn-sm" data-rerun="${esc(j.id)}"
                      ${['running', 'pending', 'stopping'].includes(j.status) ? 'disabled' : ''}>Re-run</button></td>
                  </tr>`).join('')}</tbody></table></div>`
            : '<div class="empty">Chưa có job nào được ghi lại</div>'
        }
      </div>
    </div>
  `;

  document.getElementById('btn-history-refresh')?.addEventListener('click', () => renderHistory(root));
  root.querySelectorAll('[data-rerun]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await rerunJob(btn.dataset.rerun);
        toast(`Đã start lại job ${res.job?.id || ''}`, 'ok');
        location.hash = '#/register';
      } catch (e) {
        toast(e.message || String(e), 'err');
        btn.disabled = false;
      }
    });
  });
}

async function renderProxy(root) {
  let st;
  try {
    st = await getProxies();
  } catch (e) {
    root.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }

  root.innerHTML = `
    <div class="page">
      <div class="card" style="max-width:880px">
        <div class="card-head">
          <div>
            <div class="card-title">Pool proxy dùng chung</div>
            <div class="card-sub">Bật lên thì mọi tool khi bấm Start đều chạy qua proxy ở đây: Grok + Claude, HeyGen, CapCut, Z.ai, Canva, Netflix, Manus, Notion (tự ghi vào config.json của từng tool). GPT-TOOL :8083 nhận pool đồng bộ qua API riêng.</div>
          </div>
          <span class="stat-card ${st.enabled ? 'ok' : ''}" style="min-width:110px;text-align:center;padding:8px 12px">
            <div class="stat-label">Trạng thái</div>
            <div class="stat-value" style="font-size:16px">${st.enabled ? 'ĐANG BẬT' : 'TẮT'}</div>
          </span>
        </div>

        <div class="results-toolbar">
          <label class="check-row" style="gap:8px;white-space:nowrap">
            <input type="checkbox" id="proxy-enabled" ${st.enabled ? 'checked' : ''} />
            <span>Bật cho mọi tool</span>
          </label>
          <select id="proxy-mode">
            <option value="rotate" ${st.mode !== 'fixed' ? 'selected' : ''}>Xoay vòng (mỗi Start 1 proxy)</option>
            <option value="fixed" ${st.mode === 'fixed' ? 'selected' : ''}>Cố định (luôn dòng đầu)</option>
          </select>
          <button class="btn btn-primary" id="btn-proxy-save" type="button">Lưu</button>
        </div>

        <label class="input-group" style="display:block;margin-top:14px">
          <span class="input-label">Danh sách proxy — mỗi dòng 1 proxy, mọi định dạng đều nhận</span>
          <textarea id="proxy-list" rows="9" spellcheck="false"
            style="width:100%;background:#0b0e14;color:#e6edf3;border:1px solid #262d3a;border-radius:8px;padding:10px;font-family:ui-monospace,Consolas,monospace;font-size:13px"
            placeholder="11.22.33.44:8080&#10;user:pass@45.77.10.5:3128&#10;http://user:pass@45.77.10.5:3128&#10;https://103.1.2.3:8443&#10;socks5://user:pass@103.1.2.3:1080&#10;socks4://103.1.2.3:1080">${esc((st.proxies || []).join('\n'))}</textarea>
        </label>

        <div class="card-sub" style="margin-top:10px">
          ${st.count ? `${st.count} proxy trong pool · dòng đầu: ${esc(st.next || '')}` : 'Pool đang trống — dán proxy vào rồi Lưu.'}
        </div>
        <div class="card-sub" style="margin-top:4px">
          Mẹo: nhận đủ các dạng — <code>host:port</code> · <code>user:pass@host:port</code> · <code>http://</code> · <code>https://</code> · <code>socks5://</code> · <code>socks4://</code> (có/không user:pass). Dòng thiếu scheme tự hiểu là http://, thiếu port tự điền theo scheme. Lưu sai cú pháp sẽ báo đúng dòng lỗi, mật khẩu trong log luôn bị che.
        </div>
      </div>
    </div>
  `;

  const btnSave = document.getElementById('btn-proxy-save');
  if (btnSave) {
    btnSave.addEventListener('click', async () => {
      const payload = {
        enabled: document.getElementById('proxy-enabled').checked,
        mode: document.getElementById('proxy-mode').value,
        proxies_text: document.getElementById('proxy-list').value,
      };
      if (payload.enabled && !payload.proxies_text.trim()) {
        toast('Pool trống — nhập ít nhất 1 proxy trước khi bật', 'err');
        return;
      }
      btnSave.disabled = true;
      try {
        const r = await saveProxies(payload);
        toast(`Đã lưu (${r.count} proxy) · ${r.gpt_tool || ''}`, r.enabled ? 'ok' : '');
        await renderProxy(root);
      } catch (e) {
        toast(e.message || String(e), 'err');
      } finally {
        btnSave.disabled = false;
      }
    });
  }
}

async function renderResults(root) {
  const toolId = state.selectedTool || 'grok';
  let rows = [];
  let stats = {};
  try {
    const r = await getToolResults(toolId, 2000);
    rows = r.results || [];
    stats = await getToolStats(toolId);
  } catch (e) {
    root.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }

  root.innerHTML = `
    <div class="page">
      <div class="grid-4">
        <div class="stat-card info"><div class="stat-label">Email unique</div><div class="stat-value">${stats.unique_emails ?? stats.total ?? 0}</div>
          <div class="card-sub" style="margin-top:4px">${stats.attempts ?? 0} lượt thử</div></div>
        <div class="stat-card ok"><div class="stat-label">Reg OK</div><div class="stat-value">${stats.success ?? 0}</div>
          <div class="card-sub" style="margin-top:4px">${isSheetOnly(toolId) ? 'không Sub2 — chỉ sheet' : `reg-only ${stats.reg_only ?? 0} · sub2 fail ${stats.sub2_fail ?? 0}`}</div></div>
        <div class="stat-card"><div class="stat-label">${isSheetOnly(toolId) ? `Sheet ${esc(toolId)}` : 'Sub2API OK'}</div><div class="stat-value">${isSheetOnly(toolId) ? (stats.success ?? 0) : (stats.sub2api ?? 0)}</div></div>
        <div class="stat-card bad"><div class="stat-label">Fail</div><div class="stat-value">${stats.fail ?? 0}</div>
          <div class="card-sub" style="margin-top:4px">pending ${stats.pending ?? 0}</div></div>
      </div>
      ${stats.blurb ? `<div class="card-sub">${esc(stats.blurb)}</div>` : ''}
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Accounts · ${esc(toolId)}</div>
            <div class="card-sub">data/accounts.txt — mỗi dòng = 1 lượt thử · hiển thị tối đa 2000 dòng mới nhất</div>
          </div>
          <div class="btn-row" style="margin:0">
            <button class="btn btn-ghost" id="btn-copy-ok">Copy Reg OK</button>
            <button class="btn btn-primary" id="btn-export-csv">Export CSV</button>
          </div>
        </div>
        <div class="results-toolbar">
          <input type="text" id="results-search" placeholder="Tìm email, status, ghi chú…" value="${esc(state.resultsFilter.q)}" />
          <select id="results-status">
            <option value="all" ${state.resultsFilter.st === 'all' ? 'selected' : ''}>Tất cả</option>
            <option value="ok" ${state.resultsFilter.st === 'ok' ? 'selected' : ''}>Reg OK</option>
            <option value="fail" ${state.resultsFilter.st === 'fail' ? 'selected' : ''}>Fail</option>
            <option value="pending" ${state.resultsFilter.st === 'pending' ? 'selected' : ''}>Pending</option>
          </select>
          <span class="card-sub" id="results-count"></span>
        </div>
        <div class="table-wrap">
          <table class="results">
            <thead>
              <tr><th>Email</th><th>Password</th><th>Status</th><th>Gói / ghi chú</th></tr>
            </thead>
            <tbody id="results-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  const paint = () => {
    const shown = filterRows(rows);
    const body = document.getElementById('results-body');
    const count = document.getElementById('results-count');
    if (count) count.textContent = `${shown.length} / ${rows.length} dòng`;
    if (!body) return;
    body.innerHTML = shown.length
      ? shown
          .map(
            (r) => `<tr>
              <td class="mono">${esc(r.email)}</td>
              <td class="mono">${esc(r.password)}</td>
              <td>${statusTag(r.status, r.ok)}</td>
              <td class="mono">${esc(r.extra || r.offer || r.plan || '')}</td>
            </tr>`
          )
          .join('')
      : `<tr><td colspan="4" class="empty">Không có dòng nào khớp bộ lọc</td></tr>`;
  };
  paint();

  document.getElementById('results-search')?.addEventListener('input', (e) => {
    state.resultsFilter.q = e.target.value;
    paint();
  });
  document.getElementById('results-status')?.addEventListener('change', (e) => {
    state.resultsFilter.st = e.target.value;
    paint();
  });
  document.getElementById('btn-export-csv')?.addEventListener('click', () => {
    const shown = filterRows(rows);
    if (!shown.length) {
      toast('Không có dòng nào để export', 'err');
      return;
    }
    downloadCsv(shown, `accounts_${toolId}_${new Date().toISOString().slice(0, 10)}.csv`);
    toast(`Đã export ${shown.length} dòng CSV`, 'ok');
  });

  document.getElementById('btn-copy-ok')?.addEventListener('click', async () => {
    const text = rows
      .filter((r) => r.ok)
      .map((r) => `${r.email}|${r.password}|${r.status}`)
      .join('\n');
    try {
      await navigator.clipboard.writeText(text || '');
      toast(`Đã copy ${rows.filter((r) => r.ok).length} dòng`, 'ok');
    } catch {
      toast('Copy thất bại', 'err');
    }
  });
}

async function renderLogs(root) {
  const job = state.job;
  root.innerHTML = `
    <div class="page">
      <div class="card">
        <div class="log-head">
          <div>
            <div class="card-title">Full log stream</div>
            <div class="card-sub" id="job-status-line">${job ? `${esc(job.tool_id)} · ${esc(job.status)} · id ${esc(job.id || '')}` : 'Idle'}</div>
          </div>
          <div class="btn-row" style="margin:0">
            <label class="check-row" style="padding:6px 10px;margin:0">
              <input type="checkbox" id="auto-scroll" ${state.autoScroll ? 'checked' : ''} />
              <span style="font-size:12px">Auto-scroll</span>
            </label>
            <button class="btn btn-danger" id="btn-stop-log">⏹ Stop</button>
            <button class="btn btn-ghost" id="btn-copy-log" type="button">Copy log</button>
            <button class="btn btn-ghost" id="btn-clear-view">Clear view</button>
          </div>
        </div>
        <div class="log-console" id="log-box" style="height:calc(100vh - 220px)"></div>
      </div>
    </div>
  `;
  const fullBox = document.getElementById('log-box');
  bindLogBox(fullBox);
  paintLogs(fullBox, job?.logs || []);
  document.getElementById('auto-scroll')?.addEventListener('change', (e) => {
    setAutoScroll(e.target.checked, { scrollBox: document.getElementById('log-box') });
  });
  document.getElementById('btn-copy-log')?.addEventListener('click', async () => {
    try {
      await copyLogBox(document.getElementById('log-box'));
    } catch {
      toast('Copy thất bại', 'err');
    }
  });
  document.getElementById('btn-stop-log')?.addEventListener('click', async () => {
    try {
      await stopJob();
      toast('Stop sent', 'ok');
    } catch (e) {
      toast(e.message, 'err');
    }
  });
  document.getElementById('btn-clear-view')?.addEventListener('click', () => {
    const box = document.getElementById('log-box');
    if (box) box.innerHTML = '';
  });
}

async function renderSettings(root) {
  let sum = {};
  try {
    sum = await getConfigSummary();
  } catch (e) {
    root.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    return;
  }
  const sub = sum.sub2api || {};
  const gs = sum.google_sheets || {};
  root.innerHTML = `
    <div class="page">
      <div class="grid-2">
        <div class="card">
          <div class="card-title" style="margin-bottom:14px">Sub2API</div>
          <dl class="kv">
            <dt>Enabled</dt><dd>${sub.enabled ? 'Yes' : 'No'}</dd>
            <dt>Mode</dt><dd class="mono">${esc(sub.mode)}</dd>
            <dt>URL</dt><dd class="mono">${esc(sub.url)}</dd>
            <dt>Group</dt><dd>${esc(sub.group)}</dd>
            <dt>Name prefix</dt><dd>${esc(sub.name_prefix)}</dd>
            <dt>User</dt><dd class="mono">${esc(sub.user)}</dd>
          </dl>
          <p class="card-sub" style="margin-top:14px">Sửa chi tiết trong <span class="mono">config.json</span> · mode=auto ưu tiên SSO API.</p>
        </div>
        <div class="card">
          <div class="card-title" style="margin-bottom:14px">Google Sheet & Session</div>
          <dl class="kv">
            <dt>Sheet</dt><dd>${gs.enabled ? 'On' : 'Off'}</dd>
            <dt>Spreadsheet</dt><dd class="mono">${esc(gs.spreadsheet_id)}</dd>
            <dt>Webapp</dt><dd>${gs.webapp_set ? 'Configured' : '—'}</dd>
            <dt>Force guest</dt><dd>${sum.force_guest_on_start ? 'Yes' : 'No'}</dd>
            <dt>Open Grok after</dt><dd>${sum.open_grok_after_success ? 'Yes' : 'No'}</dd>
            <dt>Fixed password</dt><dd>${sum.fixed_password_set ? 'Set' : '—'}</dd>
          </dl>
        </div>
      </div>
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Turnstile Solver</div>
            <div class="card-sub">Camoufox :5072 — monitor tự restart khi offline</div>
          </div>
          <div class="btn-row" style="margin:0">
            <button class="btn btn-primary" id="btn-solver-restart">Restart</button>
            <button class="btn btn-ghost" id="btn-solver-start">Start</button>
            <button class="btn btn-danger" id="btn-solver-stop">Stop</button>
          </div>
        </div>
        <dl class="kv" style="margin-top:10px">
          <dt>Trạng thái</dt><dd id="solver-status-line">…</dd>
          <dt>URL</dt><dd class="mono" id="solver-url">http://127.0.0.1:5072</dd>
          <dt>PID</dt><dd class="mono" id="solver-pid">—</dd>
        </dl>
        <p class="card-sub" id="solver-last-error" style="color:var(--error)" hidden></p>
        <p class="card-sub" style="margin-top:10px">Solver offline ≥1 phút → tự bật lại và gửi notification (nếu đã cấu hình Telegram/webhook trong <span class="mono">config.json → notify</span>).</p>
      </div>
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Docker</div>
            <div class="card-sub">Docker Desktop & container — Sub2API thường chạy ở đây</div>
          </div>
          <div class="btn-row" style="margin:0">
            <button class="btn btn-primary" id="btn-docker-daemon">Bật Docker</button>
            <button class="btn btn-ghost" id="btn-docker-refresh">Refresh</button>
          </div>
        </div>
        <dl class="kv" style="margin-top:10px">
          <dt>Trạng thái</dt><dd id="docker-status-line">…</dd>
          <dt>Version</dt><dd class="mono" id="docker-version">—</dd>
        </dl>
        <div id="docker-containers" style="margin-top:10px"></div>
        <p class="card-sub" style="margin-top:10px">Docker tắt → bấm <strong>Bật Docker</strong>, chờ ~30s rồi Refresh. Container nào đang <span class="mono">exited</span> thì bấm Start để chạy lại.</p>
      </div>
      <div class="card">
        <div class="card-title" style="margin-bottom:8px">Thêm tool mới</div>
        <p class="card-sub" style="margin-bottom:12px">
          Tạo file <span class="mono">web_console/plugins/your_tool.py</span> kế thừa <span class="mono">BaseToolPlugin</span>,
          rồi đăng ký trong <span class="mono">plugins/__init__.py</span>. UI tự hiện tile + form fields.
        </p>
        <pre class="log-console" style="height:auto;max-height:220px;padding:14px">class MyTool(BaseToolPlugin):
    meta = ToolMeta(id="mytool", name="My Tool", ...)
    def build_command(self, params, root): ...
    def parse_results(self, root, limit=200): ...</pre>
      </div>
    </div>
  `;

  const solverBtn = async (action) => {
    try {
      const res = await solverAction(action);
      toast(res.message || `Đang ${action} solver…`, 'ok');
      setTimeout(refreshSolverPill, 3000);
    } catch (e) {
      toast(e.message || String(e), 'err');
    }
  };
  document.getElementById('btn-solver-restart')?.addEventListener('click', () => solverBtn('restart'));
  document.getElementById('btn-solver-start')?.addEventListener('click', () => solverBtn('start'));
  document.getElementById('btn-solver-stop')?.addEventListener('click', () => solverBtn('stop'));
  paintSolverCard(state.solver);
  refreshSolverPill();

  /* ── Docker ── */
  const dockerActionRun = async (action, name = null) => {
    try {
      const res = await api.dockerAction(action, name);
      toast(res.message || `Đang ${action}…`, 'ok');
      if (action !== 'start_daemon') setTimeout(refreshDocker, 4000);
    } catch (e) {
      toast(e.message || String(e), 'err');
    }
  };
  const refreshDocker = async () => {
    try {
      const st = await api.getDockerStatus();
      const line = document.getElementById('docker-status-line');
      const ver = document.getElementById('docker-version');
      const wrap = document.getElementById('docker-containers');
      if (!line || !wrap) return;
      if (!st.installed) {
        line.innerHTML = '<span class="tag tag-fail">chưa cài</span>';
        ver.textContent = '—';
        wrap.innerHTML = '<div class="hint">Cài Docker Desktop rồi restart web console.</div>';
        return;
      }
      line.innerHTML = st.daemon_running
        ? '<span class="tag tag-ok">running</span>'
        : (st.desktop_found
          ? '<span class="tag tag-fail">daemon off</span> <span class="hint">— bấm Bật Docker</span>'
          : '<span class="tag tag-fail">daemon off</span>');
      ver.textContent = st.version || '—';
      const rows = (st.containers || [])
        .map((c) => `
          <div class="mail-row" style="flex-direction:row;align-items:center;justify-content:space-between">
            <div style="min-width:0">
              <span class="mail-subj mono">${esc(c.name)}</span>
              <div class="hint">${esc(c.image)} · ${esc(c.status)}</div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;flex:none">
              ${c.state === 'running'
                ? '<span class="tag tag-ok">up</span>'
                : '<span class="tag tag-mid">' + esc(c.state || 'off') + '</span>'}
              ${c.state === 'running'
                ? `<button class="btn btn-danger" style="min-height:32px;padding:4px 10px" data-docker-act="stop" data-docker-name="${esc(c.name)}">Stop</button>
                   <button class="btn btn-ghost" style="min-height:32px;padding:4px 10px" data-docker-act="restart" data-docker-name="${esc(c.name)}">Restart</button>`
                : `<button class="btn btn-primary" style="min-height:32px;padding:4px 10px" data-docker-act="start" data-docker-name="${esc(c.name)}">Start</button>`}
            </div>
          </div>`)
        .join('');
      wrap.innerHTML = st.daemon_running && st.containers.length
        ? rows
        : '<div class="hint">Không thấy container nào — daemon chưa chạy hoặc chưa có container.</div>';
    } catch (_) {
      /* API offline — giữ nguyên */
    }
  };
  document.getElementById('btn-docker-daemon')?.addEventListener('click', () => dockerActionRun('start_daemon'));
  document.getElementById('btn-docker-refresh')?.addEventListener('click', refreshDocker);
  document.getElementById('docker-containers')?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-docker-act]');
    if (!btn) return;
    dockerActionRun(btn.dataset.dockerAct, btn.dataset.dockerName);
  });
  refreshDocker();
}

async function renderTools(root) {
  if (!state.tools.length) {
    const data = await getTools();
    state.tools = data.tools || [];
  }
  root.innerHTML = `
    <div class="page">
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Plugin registry</div>
            <div class="card-sub">Các tool gắn vào control plane. Placeholder = sắp làm.</div>
          </div>
        </div>
        <div class="tool-grid">
          ${state.tools
            .map((t) => {
              const soon = t.status === 'coming_soon';
              return `<div class="tool-tile ${soon ? 'is-soon' : ''}" style="cursor:default">
                ${brandIconHtml(t)}
                <strong>${esc(t.name)}</strong>
                <p>${esc(t.description)}</p>
                <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
                  <span class="badge ${soon ? 'badge-soon' : 'badge-ready'}">${soon ? 'Coming soon' : 'Ready'}</span>
                  <span class="mono" style="font-size:11px;color:var(--text-muted)">${esc(t.id)}</span>
                </div>
              </div>`;
            })
            .join('')}
        </div>
      </div>
    </div>
  `;
}

/* ── Router ── */
async function route() {
  state.routeToken += 1; // đánh dấu lượt điều hướng — bỏ fetch cũ đang chạy
  const hash = location.hash || '#/register';
  const known = PAGE_META[hash] ? hash : '#/register';
  if (known !== location.hash) location.hash = known;
  setActiveNav(known);
  const main = document.getElementById('main-content');
  if (!main) return;
  main.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    if (known === '#/register') await renderRegister(main);
    else if (known === '#/dashboard') await renderDashboard(main);
    else if (known === '#/history') await renderHistory(main);
    else if (known === '#/results') await renderResults(main);
    else if (known === '#/logs') await renderLogs(main);
    else if (known === '#/proxy') await renderProxy(main);
    else if (known === '#/settings') await renderSettings(main);
    else if (known === '#/tools') await renderTools(main);
  } catch (e) {
    main.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`;
  }
}

/* ── Job snapshots: SSE push + REST fallback ── */

// SSE gửi chunk tăng dần (log_from=last_seq), không gửi lại toàn bộ log.
// mergeJobLogs nối chunk vào state.jobLogs dựa trên log_seq; window đầy
// (reconnect / poll / job mới) thì thay bằng window mới nhất.
function mergeJobLogs(snap) {
  const id = snap.id ?? null;
  const seq = snap.log_seq ?? 0;
  const chunk = Array.isArray(snap.logs) ? snap.logs : [];
  if (id !== state.jobId) {
    // job đổi (hoặc lần đầu) — bắt đầu log mới
    state.jobId = id;
    state.jobLogs = chunk;
    state.logSeq = seq;
    return state.jobLogs;
  }
  // bản tin cũ / lặp lại — giữ nguyên
  if (seq <= state.logSeq) return state.jobLogs;
  const delta = seq - state.logSeq;
  if (delta === chunk.length) {
    // chunk tăng dần — nối tiếp
    state.jobLogs = (state.jobLogs || []).concat(chunk);
  } else {
    // gap / window đầy (reconnect, poll, buffer tràn) — thay bằng chunk mới
    state.jobLogs = chunk;
  }
  state.logSeq = seq;
  if (state.jobLogs.length > 4000) state.jobLogs = state.jobLogs.slice(-4000);
  return state.jobLogs;
}

function applyJobSnapshot(snap, opts = {}) {
  if (!snap || typeof snap !== 'object') return;
  if (Array.isArray(snap.queue)) state.queue = snap.queue;
  if (snap.status && snap.status !== 'idle') {
    state.job = snap;
  } else if (Array.isArray(snap.logs) && snap.logs.length) {
    state.job = snap; // job cuối với log — giữ hiển thị
  }
  updateRunPill(state.job);

  const box = document.getElementById('log-box');
  const statusLine = document.getElementById('job-status-line');
  if (state.job) {
    const qn = (state.queue || []).length;
    if (statusLine) {
      statusLine.textContent = `${state.job.tool_id || ''} · ${state.job.status || ''}${
        state.job.id ? ' · ' + state.job.id : ''
      }${qn ? ` · queue ${qn}` : ''}`;
    }
    // gom log kể cả khi đang ở trang khác — paint chỉ khi có hộp log
    mergeJobLogs(state.job);
    // paint gom theo frame thay vì vẽ ngay từng bản tin SSE
    if (box && !opts.skipLogs) scheduleLogPaint(box);
  }

  // Start/Stop state: Start luôn bật (xếp hàng được), Stop chỉ bật khi đang chạy
  const running =
    state.job && ['running', 'pending', 'stopping'].includes(state.job.status);
  const bs = document.getElementById('btn-start');
  const bt = document.getElementById('btn-stop');
  if (bs && bs.dataset.locked !== undefined) bs.disabled = bs.dataset.locked === '1';
  if (bt) bt.disabled = !running;
}

function startEventStream() {
  if (!window.EventSource) {
    // trình duyệt cũ — dùng poll như cũ
    state.pollTimer = setInterval(pollJob, 1500);
    return;
  }
  const es = new EventSource('/api/logs/stream');
  state.es = es;
  es.onmessage = (ev) => {
    try {
      applyJobSnapshot(JSON.parse(ev.data));
    } catch (_) {
      /* payload lạ — bỏ qua */
    }
  };
  // EventSource tự reconnect; không cần onerror handler
}

async function pollJob() {
  try {
    const snap = await getCurrentJob(0);
    // SSE đang sống thì poll chỉ đồng bộ status/queue — không đụng log
    // (snapshot log_from=0 là window 300 dòng, thay vào sẽ làm mất log đã gom)
    const sseAlive = state.es && state.es.readyState === EventSource.OPEN;
    applyJobSnapshot(snap, { skipLogs: sseAlive });
  } catch (_) {
    /* ignore poll errors */
  }
}

async function boot() {
  initChrome();
  window.addEventListener('hashchange', () => route());
  try {
    await getHealth();
    const data = await getTools();
    state.tools = data.tools || [];
  } catch (e) {
    toast('API offline: ' + e.message, 'err');
  }
  await route();
  startEventStream();
  await pollJob();
  refreshSolverPill();
  // fallback: SSE mất kết nối lâu / refresh đèn solver + queue
  state.pollTimer = setInterval(async () => {
    await pollJob();
    refreshSolverPill();
  }, 20000);
}

boot();
