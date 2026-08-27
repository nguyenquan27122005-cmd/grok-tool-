export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg =
      (data && (data.detail || data.message || data.error)) ||
      res.statusText ||
      'Request failed';
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

export const getTools = () => api('/api/tools');
export const getToolStats = (id) => api(`/api/tools/${id}/stats`);
export const getToolResults = (id, limit = 100) =>
  api(`/api/tools/${id}/results?limit=${limit}`);
export const getCurrentJob = (logFrom = 0) =>
  api(`/api/jobs/current?log_from=${logFrom}`);
export const startJob = (tool_id, params) =>
  api('/api/jobs/start', {
    method: 'POST',
    body: JSON.stringify({ tool_id, params }),
  });
export const stopJob = (job_id = null) =>
  api('/api/jobs/stop', {
    method: 'POST',
    body: JSON.stringify({ job_id }),
  });
export const getConfigSummary = () => api('/api/config/summary');
export const getHealth = () => api('/api/health');
export const getProxies = () => api('/api/proxies');
export const saveProxies = (payload) =>
  api('/api/proxies', { method: 'POST', body: JSON.stringify(payload) });
export const getHotmails = (id) => api(`/api/tools/${id}/hotmails`);
export const importHotmails = (id, text, mode = 'append') =>
  api(`/api/tools/${id}/hotmails`, {
    method: 'POST',
    body: JSON.stringify({ text, mode }),
  });
export const getSolverStatus = () => api('/api/solver');
export const solverAction = (action) =>
  api('/api/solver', {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
export const listJobs = () => api('/api/jobs');
export const getDashboard = (days = 14) => api(`/api/dashboard?days=${days}`);
export const getHealthAccounts = () => api('/api/health/accounts');
export const runHealthCheck = () =>
  api('/api/health/run', { method: 'POST', body: JSON.stringify({}) });
export const getBackups = () => api('/api/backups');
export const runBackup = () =>
  api('/api/backups/run', { method: 'POST', body: JSON.stringify({}) });
export const rerunJob = (jobId, params = null) =>
  api(`/api/jobs/${jobId}/rerun`, {
    method: 'POST',
    body: JSON.stringify(params ? { params } : {}),
  });
export const getDockerStatus = () => api('/api/docker');
export const dockerAction = (action, name = null) =>
  api('/api/docker', { method: 'POST', body: JSON.stringify({ action, name }) });
export const lookupMail = (address) =>
  api(`/api/mail/lookup?address=${encodeURIComponent(address)}`);
