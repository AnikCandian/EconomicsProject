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

// Client-side mirror of dataset.fully_selected_categories() -- which
// one-hot fields (if any) have every one of their categories checked at
// once, the classic dummy-variable trap. Checked before ever POSTing to
// /finalize so a student can't submit it in the first place; the server
// enforces the same rule independently (see API_PROTOCOL.md, "Attempts")
// in case this check is ever bypassed or `categories` is stale.
function fullySelectedCategories(variables, categories) {
  const chosen = new Set(variables);
  return Object.entries(categories)
    .filter(([category, values]) => values.every((value) => chosen.has(`${category}_${value}`)))
    .map(([category]) => category);
}

// Mirrors dataset.dummy_variable_trap_message() server-side, so the banner
// reads the same whether the client caught this before submitting or the
// server caught it (e.g. after a lost /finalize response, confirmed via
// GET /status's last_invalid_selection).
function dummyVariableTrapMessage(culpritCategories) {
  const named = culpritCategories.join(" and ");
  return (
    `Can't build a model with every ${named} option selected — that's the dummy variable trap ` +
    `(perfect multicollinearity from one-hot encoding). Deselect at least one ${named} option and try again.`
  );
}
