// Thin wrapper around fetch() for calling the REST backend (see
// ../../API_PROTOCOL.md). Every page loads this before its own script.

async function apiRequest(path, { method = "GET", headers = {}, body } = {}) {
  const response = await fetch(window.API_BASE_URL + path, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const error = new Error(data.detail || `Request failed (HTTP ${response.status})`);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}
