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
