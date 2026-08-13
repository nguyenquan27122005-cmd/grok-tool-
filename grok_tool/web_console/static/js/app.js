import * as api from './api.js?v=1.5';
import { toast } from './toast.js?v=1.5';

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

const PAGE_META = {
  '#/register': { title: 'Đăng ký', eyebrow: 'Task Console' },
  '#/results': { title: 'Kết quả', eyebrow: 'Accounts & Status' },
  '#/logs': { title: 'Logs', eyebrow: 'Live Stream' },
  '#/settings': { title: 'Cài đặt', eyebrow: 'System Config' },
  '#/tools': { title: 'Tools', eyebrow: 'Plugin Registry' },
};

const state = {
  tools: [],
  selectedTool: 'grok',
  form: {},
  job: null,
  logSeq: 0,
  pollTimer: null,
  autoScroll: true,
  hotmailDraft: '',
  hotmailPool: null,
};

function isHotmailMail(val) {
  const v = String(val ?? '').trim().toLowerCase();
  return v === '1' || v === 'hotmail' || v === 'outlook' || v === 'ms';
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
  document.title = `${meta.title} · Reg Control Plane`;
}

function updateRunPill(job) {
  const pill = document.getElementById('run-pill');
  const text = document.getElementById('run-pill-text');
  if (!pill || !text) return;
  const running = job && ['running', 'pending', 'stopping'].includes(job.status);
  pill.classList.toggle('is-running', !!running);
  if (!job || job.status === 'idle') text.textContent = 'Idle';
  else text.textContent = `${job.tool_id || 'job'} · ${job.status}`;
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

function hotmailPlanText(pool) {
  const acc = Number(pool?.count ?? 0);
  const slots = Number(pool?.slots ?? acc);
  const maxA = Number(pool?.max_aliases ?? 5);
  if (!acc) return 'Pool trống — import Hotmail rồi Start.';
  return `Sẽ reg <strong>${slots}</strong> acc Grok từ ${acc} Hotmail (mỗi acc tối đa ${maxA} alias).`;
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

function hotmailPanelHtml(pool, show) {
  const acc = pool?.accounts || [];
  const count = pool?.count ?? acc.length;
  const maxA = pool?.max_aliases ?? 5;
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
  return `
    <div class="hotmail-panel" id="hotmail-pool" ${show ? '' : 'hidden'}>
      <div class="card-head" style="margin-bottom:10px">
        <div>
          <div class="card-title">Pool Hotmail</div>
          <div class="card-sub">
            ${count} Hotmail · Start sẽ reg ${pool?.slots ?? count} Grok (×${maxA} alias) ·
            <span class="mono">${esc(pool?.path || 'data/hotmails.txt')}</span>
          </div>
        </div>
      </div>
      <div class="field">
        <label>Dán Hotmail vào đây</label>
        <textarea id="hotmail-draft" rows="7" placeholder="email|password|refresh_token|client_id
email----password----client_id----refresh_token">${esc(state.hotmailDraft || '')}</textarea>
        <div class="hint">1 dòng = 1 acc = 1 lượt reg. Hỗ trợ <span class="mono">|</span> hoặc <span class="mono">----</span>. Alias +1…+${Math.max(0, maxA - 1)} dùng ở lần Start sau (còn slot).</div>
      </div>
      <div class="btn-row" style="margin:8px 0 12px">
        <button type="button" class="btn btn-ghost" id="btn-hotmail-browse">📂 Browse file…</button>
        <button type="button" class="btn btn-primary" id="btn-hotmail-add">＋ Thêm vào pool</button>
        <button type="button" class="btn btn-ghost" id="btn-hotmail-replace">Ghi đè pool</button>
        <input type="file" id="hotmail-file" accept=".txt,.csv,.tsv,.log,.text,text/plain" hidden />
      </div>
      <div class="hotmail-list-wrap">
        <div class="card-sub" style="margin-bottom:6px">Đang trong pool</div>
        ${
          acc.length
            ? `<ul class="hotmail-list">${rows}${
                acc.length > 40 ? `<li class="card-sub">… +${acc.length - 40} acc nữa</li>` : ''
              }</ul>`
            : `<div class="empty" style="padding:16px">Pool trống — dán list hoặc Browse từ Explorer.</div>`
        }
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

  let stats = {};
  try {
    if (tool.status === 'ready') stats = await getToolStats(tool.id);
  } catch (_) {}
  if (tool.id === 'grok') {
    try {
      state.hotmailPool = await getHotmails(tool.id);
    } catch (_) {
      state.hotmailPool = state.hotmailPool || { count: 0, accounts: [] };
    }
  }

  const job = state.job;
  const running = job && ['running', 'pending', 'stopping'].includes(job.status);

  root.innerHTML = `
    <div class="page">
      <div class="grid-4">
        <div class="stat-card info" title="Số email khác nhau (lấy status lần cuối)">
          <div class="stat-label">Email (unique)</div>
          <div class="stat-value">${stats.unique_emails ?? stats.total ?? '—'}</div>
          <div class="card-sub" style="margin-top:4px">${stats.attempts ?? '—'} lượt thử</div>
        </div>
        <div class="stat-card ok" title="Reg xong: Sub2API + reg-only + reg OK nhưng sub2 fail">
          <div class="stat-label">Reg OK</div>
          <div class="stat-value">${stats.success ?? '—'}</div>
          <div class="card-sub" style="margin-top:4px">chỉ reg: ${stats.reg_only ?? 0} · sub2 fail: ${stats.sub2_fail ?? 0}</div>
        </div>
        <div class="stat-card" title="Đã import Sub2API (added_sub2api)">
          <div class="stat-label">Sub2API OK</div>
          <div class="stat-value">${stats.sub2api ?? '—'}</div>
          <div class="card-sub" style="margin-top:4px">trong ${stats.success ?? 0} reg OK</div>
        </div>
        <div class="stat-card bad" title="error* lần status cuối mỗi email">
          <div class="stat-label">Fail</div>
          <div class="stat-value">${stats.fail ?? '—'}</div>
          <div class="card-sub" style="margin-top:4px">pending: ${stats.pending ?? 0}</div>
        </div>
      </div>
      ${stats.blurb ? `<div class="card-sub" style="margin-top:-6px">${esc(stats.blurb)}</div>` : ''}

      <div class="grid-2">
        <div class="card">
          <div class="card-head">
            <div>
              <div class="card-title">Chạy task</div>
              <div class="card-sub">Chọn tool → cấu hình → Start. Stop gửi data/STOP (ESC-compatible).</div>
            </div>
          </div>

          <div class="tool-grid" style="margin-bottom:16px">
            ${state.tools
              .map((t) => {
                const soon = t.status === 'coming_soon';
                const sel = t.id === tool.id;
                return `<button type="button" class="tool-tile ${sel ? 'is-selected' : ''} ${soon ? 'is-soon' : ''}" data-tool="${esc(t.id)}" ${soon ? 'disabled' : ''}>
                  <div class="ico" style="background:color-mix(in srgb, ${esc(t.color)} 18%, transparent);color:${esc(t.color)}">${esc(t.icon)}</div>
                  <strong>${esc(t.name)}</strong>
                  <p>${esc(t.description)}</p>
                  <span class="badge ${soon ? 'badge-soon' : 'badge-ready'}" style="margin-top:8px">${soon ? 'Soon' : 'Ready'}</span>
                </button>`;
              })
              .join('')}
          </div>

          <div class="form-stack" id="tool-form">
            ${(tool.fields || [])
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
                return `<div class="field" data-field-wrap="${esc(f.key)}" ${f.key === 'count' && isHotmailMail(state.form.mail) ? 'hidden' : ''}>
                  <label>${esc(f.label)}</label>
                  <input type="${f.type === 'number' ? 'number' : 'text'}" data-key="${esc(f.key)}"
                    value="${esc(state.form[f.key] ?? f.default)}"
                    ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''} />
                  ${f.hint ? `<div class="hint">${esc(f.hint)}</div>` : ''}
                </div>`;
              })
              .join('')}
          </div>

          ${tool.id === 'grok' ? hotmailPanelHtml(state.hotmailPool, isHotmailMail(state.form.mail)) : ''}
          ${
            tool.id === 'grok'
              ? `<div class="hotmail-plan" id="hotmail-plan" ${isHotmailMail(state.form.mail) ? '' : 'hidden'}>${hotmailPlanText(state.hotmailPool)}</div>`
              : ''
          }

          <div class="btn-row">
            <button class="btn btn-primary" id="btn-start" ${running || tool.status !== 'ready' ? 'disabled' : ''}>
              ▶ Start
            </button>
            <button class="btn btn-danger" id="btn-stop" ${!running ? 'disabled' : ''}>
              ⏹ Stop
            </button>
            <button class="btn btn-ghost" id="btn-refresh-stats">↻ Stats</button>
          </div>
          ${stats.next_name ? `<div class="card-sub" style="margin-top:12px">Next Sub2API name: <span class="mono">${esc(stats.next_name)}</span> · Hotmail pool: ${stats.hotmails ?? 0}</div>` : ''}
        </div>

        <div class="card">
          <div class="log-head">
            <div>
              <div class="card-title">Live log</div>
              <div class="card-sub" id="job-status-line">${job ? `${esc(job.tool_id)} · ${esc(job.status)}` : 'Chưa có job'}</div>
            </div>
            <label class="check-row" style="padding:6px 10px;margin:0">
              <input type="checkbox" id="auto-scroll" ${state.autoScroll ? 'checked' : ''} />
              <span style="font-size:12px">Auto-scroll</span>
            </label>
          </div>
          <div class="log-console" id="log-box"></div>
        </div>
      </div>
    </div>
  `;

  paintLogs(document.getElementById('log-box'), job?.logs || []);

  root.querySelectorAll('[data-tool]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      state.selectedTool = btn.dataset.tool;
      state.form = {};
      await renderRegister(root);
    });
  });

  root.querySelectorAll('[data-key]').forEach((el) => {
    const key = el.dataset.key;
    const sync = () => {
      if (el.type === 'checkbox') state.form[key] = el.checked;
      else if (el.type === 'number') state.form[key] = el.value === '' ? 0 : Number(el.value);
      else state.form[key] = el.value;
      if (key === 'mail') syncHotmailUi(root);
    };
    el.addEventListener('change', sync);
    el.addEventListener('input', sync);
  });
  bindHotmailPanel(root, tool.id);
  syncHotmailUi(root);

  document.getElementById('auto-scroll')?.addEventListener('change', (e) => {
    state.autoScroll = e.target.checked;
  });

  document.getElementById('btn-start')?.addEventListener('click', async () => {
    try {
      // collect form
      root.querySelectorAll('[data-key]').forEach((el) => {
        const key = el.dataset.key;
        if (el.type === 'checkbox') state.form[key] = el.checked;
        else if (el.type === 'number') state.form[key] = Number(el.value);
        else state.form[key] = el.value;
      });
      if (isHotmailMail(state.form.mail)) {
        try {
          state.hotmailPool = await getHotmails(state.selectedTool);
        } catch (_) {}
        const n = Number(state.hotmailPool?.slots || state.hotmailPool?.count || 0);
        if (!n) {
          toast('Pool Hotmail trống / hết slot — import acc rồi Start', 'err');
          return;
        }
        state.form.count = n;
        syncHotmailUi(root);
      }
      const res = await startJob(state.selectedTool, { ...state.form });
      state.job = res.job;
      state.logSeq = 0;
      toast('Đã Start job', 'ok');
      updateRunPill(state.job);
      await renderRegister(root);
    } catch (err) {
      toast(err.message || String(err), 'err');
    }
  });

  document.getElementById('btn-stop')?.addEventListener('click', async () => {
    try {
      const res = await stopJob(state.job?.id || null);
      toast(res.message || 'Đang dừng…', 'ok');
    } catch (err) {
      toast(err.message || String(err), 'err');
    }
  });

  document.getElementById('btn-refresh-stats')?.addEventListener('click', async () => {
    await renderRegister(root);
    toast('Đã refresh stats', 'ok');
  });
}

function paintLogs(box, lines) {
  if (!box) return;
  const atBottom =
    box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = (lines || [])
    .map((l) => `<div class="line ${lineClass(l)}">${esc(l)}</div>`)
    .join('');
  if (state.autoScroll || atBottom) box.scrollTop = box.scrollHeight;
}

async function renderResults(root) {
  const toolId = state.selectedTool || 'grok';
  let rows = [];
  let stats = {};
  try {
    const r = await getToolResults(toolId, 150);
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
          <div class="card-sub" style="margin-top:4px">reg-only ${stats.reg_only ?? 0} · sub2 fail ${stats.sub2_fail ?? 0}</div></div>
        <div class="stat-card"><div class="stat-label">Sub2API OK</div><div class="stat-value">${stats.sub2api ?? 0}</div></div>
        <div class="stat-card bad"><div class="stat-label">Fail</div><div class="stat-value">${stats.fail ?? 0}</div>
          <div class="card-sub" style="margin-top:4px">pending ${stats.pending ?? 0}</div></div>
      </div>
      ${stats.blurb ? `<div class="card-sub">${esc(stats.blurb)}</div>` : ''}
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">Accounts · ${esc(toolId)}</div>
            <div class="card-sub">data/accounts.txt — mỗi dòng = 1 lượt thử (email có thể lặp)</div>
          </div>
          <button class="btn btn-ghost" id="btn-copy-ok">Copy Reg OK</button>
        </div>
        <div class="table-wrap">
          <table class="results">
            <thead>
              <tr><th>Email</th><th>Password</th><th>Status</th></tr>
            </thead>
            <tbody>
              ${
                rows.length
                  ? rows
                      .map(
                        (r) => `<tr>
                  <td class="mono">${esc(r.email)}</td>
                  <td class="mono">${esc(r.password)}</td>
                  <td>${statusTag(r.status, r.ok)}</td>
                </tr>`
                      )
                      .join('')
                  : `<tr><td colspan="3" class="empty">Chưa có kết quả</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

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
            <button class="btn btn-danger" id="btn-stop-log">⏹ Stop</button>
            <button class="btn btn-ghost" id="btn-clear-view">Clear view</button>
          </div>
        </div>
        <div class="log-console" id="log-box" style="height:calc(100vh - 220px)"></div>
      </div>
    </div>
  `;
  paintLogs(document.getElementById('log-box'), job?.logs || []);
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
                <div class="ico">${esc(t.icon)}</div>
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
  const hash = location.hash || '#/register';
  const known = PAGE_META[hash] ? hash : '#/register';
  if (known !== location.hash) location.hash = known;
  setActiveNav(known);
  const main = document.getElementById('main-content');
  if (!main) return;
  main.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    if (known === '#/register') await renderRegister(main);
    else if (known === '#/results') await renderResults(main);
    else if (known === '#/logs') await renderLogs(main);
    else if (known === '#/settings') await renderSettings(main);
    else if (known === '#/tools') await renderTools(main);
  } catch (e) {
    main.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`;
  }
}

/* ── Poll job ── */
async function pollJob() {
  try {
    const snap = await getCurrentJob(0);
    if (snap && snap.status && snap.status !== 'idle') {
      state.job = snap;
    } else if (snap && snap.running === false && state.job && state.job.running) {
      state.job = snap;
    } else if (snap && Array.isArray(snap.logs) && snap.logs.length) {
      state.job = snap;
    }
    updateRunPill(state.job);

    const box = document.getElementById('log-box');
    const statusLine = document.getElementById('job-status-line');
    if (state.job) {
      if (statusLine) {
        statusLine.textContent = `${state.job.tool_id || ''} · ${state.job.status || ''}${state.job.id ? ' · ' + state.job.id : ''}`;
      }
      if (box) paintLogs(box, state.job.logs || []);

      // refresh Start/Stop disabled state on register page without full re-render
      const running = ['running', 'pending', 'stopping'].includes(state.job.status);
      const bs = document.getElementById('btn-start');
      const bt = document.getElementById('btn-stop');
      if (bs) bs.disabled = running;
      if (bt) bt.disabled = !running;
    }
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
  await pollJob();
  state.pollTimer = setInterval(pollJob, 900);
}

boot();
