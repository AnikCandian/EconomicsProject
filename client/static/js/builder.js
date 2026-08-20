// Model builder page. Renders a checkbox per usable variable (grouped, with
// every one-hot category individually selectable -- no "toggle the whole
// field" option, matching the backend's design). No live /explore preview
// any more (that endpoint is deprecated -- see API_PROTOCOL.md,
// "Attempts"): pick variables, submit, then poll /attempts every second to
// confirm what actually landed server-side rather than trusting the POST
// response alone. Up to 3 attempts per session.

const sessionCode = localStorage.getItem("dealGame.sessionCode");
const studentToken = localStorage.getItem("dealGame.studentToken");
const usableColumns = JSON.parse(localStorage.getItem("dealGame.usableColumns") || "[]");
const categories = JSON.parse(localStorage.getItem("dealGame.categories") || "{}");
const dummyColumnCategory = JSON.parse(localStorage.getItem("dealGame.dummyColumnCategory") || "{}");

if (!sessionCode || !studentToken) {
  window.location.href = "/";
}

const studentName = localStorage.getItem("dealGame.studentName") || "";
document.getElementById("user-name").textContent = studentName;
document.getElementById("user-avatar").textContent = initialsOf(studentName);

document.getElementById("leave-btn").addEventListener("click", () => {
  localStorage.clear();
  window.location.href = "/";
});

function initialsOf(name) {
  return name.split(/\s+/).filter(Boolean).map((w) => w[0].toUpperCase()).slice(0, 2).join("");
}

let maxAttempts = Number(localStorage.getItem("dealGame.maxAttempts") || "3");
let attemptsUsed = 0;
let confirmPollHandle = null;

// ---- build the predictor groups from what /join actually returned ----

const GROUP_DEFS = [
  ["Episode & audience", ["Season Number", "Episode Number", "Pitch Number", "US Viewership"]],
  ["Pitch & entrepreneur", ["Multiple Entrepreneurs"]],
  ["The ask", ["Original Ask Amount", "Original Offered Equity", "Valuation Requested"]],
  [
    "Panel present",
    [
      "Barbara Corcoran Present", "Mark Cuban Present", "Lori Greiner Present",
      "Robert Herjavec Present", "Daymond John Present", "Kevin O Leary Present", "Guest Present",
    ],
  ],
];

function buildGroups() {
  const usable = new Set(usableColumns);
  const groups = GROUP_DEFS.map(([name, columns]) => [name, columns.filter((c) => usable.has(c))]);

  // One group per category (e.g. "Industry", "Pitchers Gender"), each value
  // individually selectable as its own dummy column.
  Object.entries(categories).forEach(([category, values]) => {
    const label = category === "Pitchers Gender" ? "Pitcher gender" : category;
    const columns = values.map((v) => `${category}_${v}`).filter((c) => usable.has(c));
    groups.push([label + " category", columns]);
  });

  return groups.filter(([, columns]) => columns.length > 0);
}

function renderGroups() {
  const container = document.getElementById("predictor-groups");
  container.innerHTML = "";

  buildGroups().forEach(([name, columns]) => {
    const group = document.createElement("div");
    group.className = "predictor-group";

    const head = document.createElement("div");
    head.className = "predictor-group__head";
    head.innerHTML = `
      <div class="predictor-group__name">${name}</div>
      <div class="predictor-group__count" data-count-for="${name}">0/${columns.length}</div>
      <button type="button" class="link-ghost" data-toggle-all="${name}" style="font-size:10px">All</button>
    `;
    group.appendChild(head);

    const list = document.createElement("div");
    list.className = "predictor-list";
    columns.forEach((column) => list.appendChild(predictorItem(column)));
    group.appendChild(list);

    container.appendChild(group);
  });

  container.querySelectorAll("[data-toggle-all]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const [, columns] = buildGroups().find(([name]) => name === btn.dataset.toggleAll);
      const allOn = columns.every((c) => document.querySelector(`input[value="${cssEscape(c)}"]`).checked);
      columns.forEach((c) => {
        document.querySelector(`input[value="${cssEscape(c)}"]`).checked = !allOn;
      });
      updateGroupCounts();
      updateRailCount();
    });
  });
}

function cssEscape(value) {
  return value.replace(/["\\]/g, "\\$&");
}

function predictorItem(column) {
  const wrapper = document.createElement("button");
  wrapper.type = "button";
  wrapper.className = "predictor-item";
  wrapper.innerHTML = `
    <span class="predictor-item__box"><span class="predictor-item__dot" hidden></span></span>
    <span class="predictor-item__label">${column}</span>
  `;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = column;
  input.hidden = true;

  wrapper.prepend(input);
  wrapper.addEventListener("click", () => {
    if (input.disabled) return;
    input.checked = !input.checked;
    wrapper.querySelector(".predictor-item__dot").hidden = !input.checked;
    updateGroupCounts();
    updateRailCount();
  });
  return wrapper;
}

function selectedVariables() {
  return Array.from(document.querySelectorAll('input[type="checkbox"]:checked')).map((el) => el.value);
}

function updateGroupCounts() {
  buildGroups().forEach(([name, columns]) => {
    const checked = columns.filter((c) => document.querySelector(`input[value="${cssEscape(c)}"]`).checked).length;
    const el = document.querySelector(`[data-count-for="${name}"]`);
    if (el) el.textContent = `${checked}/${columns.length}`;
  });
}

function updateRailCount() {
  const total = usableColumns.length;
  document.getElementById("rail-count").textContent = `${selectedVariables().length} / ${total}`;
}

// ---- rendering ----

function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function renderMetrics(metrics, equation, warning) {
  const pct = metrics ? (metrics.accuracy * 100).toFixed(1) : "—";
  document.getElementById("rail-pct").textContent = pct;
  document.getElementById("rail-bar-fill").style.width = metrics ? `${metrics.accuracy * 100}%` : "0%";
  document.getElementById("yes-pct").textContent = metrics ? fmtPct(metrics.yes_deal_accuracy) : "—";
  document.getElementById("yes-bar").style.width = metrics && metrics.yes_deal_accuracy != null ? `${metrics.yes_deal_accuracy * 100}%` : "0%";
  document.getElementById("no-pct").textContent = metrics ? fmtPct(metrics.no_deal_accuracy) : "—";
  document.getElementById("no-bar").style.width = metrics && metrics.no_deal_accuracy != null ? `${metrics.no_deal_accuracy * 100}%` : "0%";

  if (metrics) {
    const correctTotal = Math.round(metrics.accuracy * metrics.sample_size);
    document.getElementById("rail-correct").textContent = correctTotal.toLocaleString();
    document.getElementById("rail-scored").textContent = metrics.sample_size.toLocaleString();
    document.getElementById("rail-deals").textContent = fmtPct(metrics.yes_deal_accuracy);
    document.getElementById("rail-deals-meta").textContent = "recall on actual deals";
    document.getElementById("rail-nodeals").textContent = fmtPct(metrics.no_deal_accuracy);
    document.getElementById("rail-nodeals-meta").textContent = "recall on actual non-deals";
  } else {
    document.getElementById("rail-correct").textContent = "—";
    document.getElementById("rail-scored").textContent = "—";
    document.getElementById("rail-deals").textContent = "—";
    document.getElementById("rail-deals-meta").textContent = "";
    document.getElementById("rail-nodeals").textContent = "—";
    document.getElementById("rail-nodeals-meta").textContent = "";
  }

  document.getElementById("equation-text").textContent = equation || "No attempts submitted yet.";

  const railWarn = document.getElementById("rail-warning");
  const inlineWarn = document.getElementById("rail-warning-inline");
  if (warning) {
    railWarn.textContent = "⚠️ " + warning;
    railWarn.hidden = false;
    inlineWarn.textContent = "⚠️ " + warning;
    inlineWarn.hidden = false;
  } else {
    railWarn.hidden = true;
    inlineWarn.hidden = true;
  }
}

function renderAttemptsTable(attemptList) {
  const tbody = document.getElementById("attempts-rows");
  tbody.innerHTML = "";
  if (attemptList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--color-neutral-600)">No attempts yet.</td></tr>';
    return;
  }
  attemptList.forEach((a) => {
    const metrics = a.basic_test || {};
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${a.attempt_number}${a.warning ? " ⚠️" : ""}</td>
      <td>${(a.variables || []).join(", ")}</td>
      <td>${fmtPct(metrics.accuracy)}</td>
      <td>${fmtPct(metrics.yes_deal_accuracy)}</td>
      <td>${fmtPct(metrics.no_deal_accuracy)}</td>
      <td>${a.final_test ? fmtPct(a.final_test.accuracy) : "not revealed yet"}</td>
    `;
    tbody.appendChild(row);
  });
}

function updateAttemptsUi() {
  document.getElementById("attempts-counter").textContent = `${attemptsUsed} / ${maxAttempts} attempts`;
  const remaining = maxAttempts - attemptsUsed;
  if (remaining <= 0) {
    document.getElementById("exhausted-banner").hidden = false;
    setFormDisabled(true);
  } else {
    document.getElementById("submit-btn").textContent = `Submit attempt (${attemptsUsed + 1} of ${maxAttempts})`;
  }
}

function setFormDisabled(disabled) {
  document.querySelectorAll('input[type="checkbox"]').forEach((el) => (el.disabled = disabled));
  document.getElementById("submit-btn").disabled = disabled;
  document.getElementById("clear-btn").disabled = disabled;
}

async function refreshAttempts() {
  const data = await apiRequest(`/sessions/${sessionCode}/attempts`, {
    headers: { "X-Student-Token": studentToken },
  });
  attemptsUsed = data.attempts_used;
  maxAttempts = data.max_attempts;
  localStorage.setItem("dealGame.maxAttempts", String(maxAttempts));
  renderAttemptsTable(data.attempts);
  document.getElementById("result-raw").textContent = JSON.stringify(data, null, 2);
  if (data.attempts.length > 0) {
    const latest = data.attempts[data.attempts.length - 1];
    renderMetrics(latest.basic_test, latest.equation, latest.warning);
    document.getElementById("rail-status").textContent = `Attempt ${latest.attempt_number} of ${maxAttempts}`;
  }
  updateAttemptsUi();
  return data;
}

document.getElementById("submit-btn").addEventListener("click", async () => {
  const variables = selectedVariables();
  if (variables.length === 0) return alert("Select at least one variable first.");
  if (!confirm(`Submit attempt ${attemptsUsed + 1} of ${maxAttempts}? Each attempt is scored for real and can't be undone.`)) return;

  const expectedCount = attemptsUsed + 1;
  setFormDisabled(true);
  document.getElementById("pending-banner").hidden = false;
  document.getElementById("rail-status").textContent = "Submitting…";

  try {
    await apiRequest(`/sessions/${sessionCode}/finalize`, {
      method: "POST",
      headers: { "X-Student-Token": studentToken },
      body: { variables },
    });
  } catch (err) {
    // Even on a network error the attempt may have landed server-side --
    // fall through to polling /attempts rather than assuming it didn't.
    console.warn("finalize request failed, confirming via /attempts instead:", err.message);
  }

  // Poll /attempts every second until it reflects the new attempt -- this
  // is the authoritative source of truth, not the POST response above.
  confirmPollHandle = setInterval(async () => {
    try {
      const data = await refreshAttempts();
      if (data.attempts_used >= expectedCount) {
        clearInterval(confirmPollHandle);
        document.getElementById("pending-banner").hidden = true;
        if (data.attempts_remaining > 0) setFormDisabled(false);
      }
    } catch (err) {
      console.error(err);
    }
  }, 1000);
});

document.getElementById("clear-btn").addEventListener("click", () => {
  document.querySelectorAll('input[type="checkbox"]').forEach((el) => {
    el.checked = false;
    el.closest(".predictor-item").querySelector(".predictor-item__dot").hidden = true;
  });
  updateGroupCounts();
  updateRailCount();
});

// ---- poll for session close ----

async function pollStatus() {
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/status`, {
      headers: { "X-Student-Token": studentToken },
    });
    if (data.status === "closed") {
      document.getElementById("closed-banner").hidden = false;
      setFormDisabled(true);
      clearInterval(statusHandle);
      if (confirmPollHandle) clearInterval(confirmPollHandle);

      renderAttemptsTable(data.your_attempts);
      if (data.your_attempts.length > 0) {
        const latest = data.your_attempts[data.your_attempts.length - 1];
        renderMetrics(latest.basic_test, latest.equation, latest.warning);
      }

      document.getElementById("final-section").hidden = false;
      document.getElementById("final-basic-rank").textContent = data.your_basic_test_rank ?? "—";
      document.getElementById("final-final-rank").textContent = data.your_final_test_rank ?? "—";
    }
  } catch (err) {
    console.error(err);
  }
}

renderGroups();
updateRailCount();
refreshAttempts().catch((err) => console.error(err)); // restore state on page load/refresh
const statusHandle = setInterval(pollStatus, 5000);
pollStatus();
