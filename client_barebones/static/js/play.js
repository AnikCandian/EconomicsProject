// Student variable-picking page. No live /explore preview any more (that
// endpoint is deprecated -- see API_PROTOCOL.md, "Attempts"): pick
// variables, submit, then poll /attempts every second to confirm what
// actually landed server-side, rather than trusting the POST response
// alone. Up to 3 attempts per session.

const sessionCode = localStorage.getItem("dealGame.sessionCode");
const studentToken = localStorage.getItem("dealGame.studentToken");
const usableColumns = JSON.parse(localStorage.getItem("dealGame.usableColumns") || "[]");
const categories = JSON.parse(localStorage.getItem("dealGame.categories") || "{}");
const dummyColumnCategory = JSON.parse(localStorage.getItem("dealGame.dummyColumnCategory") || "{}");

if (!sessionCode || !studentToken) {
  window.location.href = "/join";
}

document.getElementById("session-code-display").textContent = sessionCode;
document.getElementById("student-name-display").textContent = localStorage.getItem("dealGame.studentId") || "";

let maxAttempts = Number(localStorage.getItem("dealGame.maxAttempts") || "3");
let attemptsUsed = 0;
let confirmPollHandle = null;

function checkboxLabel(value, labelText) {
  const label = document.createElement("label");
  label.className = "checkbox-option";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = "variables";
  input.value = value;
  label.appendChild(input);
  label.append(" " + labelText);
  return label;
}

function buildCheckboxes() {
  const categoryColumns = new Set(Object.keys(dummyColumnCategory));
  const numericColumns = usableColumns.filter((c) => !categoryColumns.has(c));

  const numericFieldset = document.getElementById("numeric-fieldset");
  numericColumns.forEach((column) => numericFieldset.appendChild(checkboxLabel(column, column)));

  const container = document.getElementById("category-fieldsets");
  Object.entries(categories).forEach(([category, values]) => {
    const fieldset = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = category;
    fieldset.appendChild(legend);
    values.forEach((value) => {
      fieldset.appendChild(checkboxLabel(`${category}_${value}`, value));
    });
    container.appendChild(fieldset);
  });
}

function selectedVariables() {
  return Array.from(document.querySelectorAll('input[name="variables"]:checked')).map((el) => el.value);
}

function setFormDisabled(disabled) {
  document.querySelectorAll('input[name="variables"]').forEach((el) => (el.disabled = disabled));
  document.getElementById("submit-btn").disabled = disabled;
}

function updateAttemptsUi() {
  document.getElementById("attempts-counter").textContent = `${attemptsUsed} / ${maxAttempts}`;
  const remaining = maxAttempts - attemptsUsed;
  const btn = document.getElementById("submit-btn");
  if (remaining <= 0) {
    document.getElementById("exhausted-banner").hidden = false;
    setFormDisabled(true);
  } else {
    btn.textContent = `Submit attempt (${attemptsUsed + 1} of ${maxAttempts})`;
  }
}

function renderLatest(attempt) {
  if (!attempt) return;
  document.getElementById("result-raw").textContent = JSON.stringify(attempt, null, 2);
  document.getElementById("result-equation").textContent = attempt.equation || "";

  const warningEl = document.getElementById("result-warning");
  if (attempt.warning) {
    warningEl.textContent = "⚠️ " + attempt.warning;
    warningEl.hidden = false;
  } else {
    warningEl.hidden = true;
  }

  const metrics = attempt.basic_test || {};
  document.getElementById("result-summary").innerHTML = `
    <dt>Attempt</dt><dd>${attempt.attempt_number} / ${maxAttempts}</dd>
    <dt>Variables</dt><dd>${(attempt.variables || []).join(", ") || "—"}</dd>
    <dt>Basic test accuracy</dt><dd>${fmtPct(metrics.accuracy)}</dd>
    <dt>Yes-deal accuracy</dt><dd>${fmtPct(metrics.yes_deal_accuracy)}</dd>
    <dt>No-deal accuracy</dt><dd>${fmtPct(metrics.no_deal_accuracy)}</dd>
    <dt>Sample size</dt><dd>${metrics.sample_size ?? "—"}</dd>
  `;
}

function renderAttemptsTable(attemptList) {
  const tbody = document.querySelector("#attempts-table tbody");
  tbody.innerHTML = "";
  if (attemptList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6"><em>No attempts yet.</em></td></tr>';
    return;
  }
  attemptList.forEach((a) => {
    const metrics = a.basic_test || {};
    const finalMetrics = a.final_test;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${a.attempt_number}${a.warning ? " ⚠️" : ""}</td>
      <td>${(a.variables || []).join(", ")}</td>
      <td>${fmtPct(metrics.accuracy)}</td>
      <td>${fmtPct(metrics.yes_deal_accuracy)}</td>
      <td>${fmtPct(metrics.no_deal_accuracy)}</td>
      <td>${finalMetrics ? fmtPct(finalMetrics.accuracy) : "not revealed yet"}</td>
    `;
    tbody.appendChild(row);
  });
}

async function refreshAttempts() {
  const data = await apiRequest(`/sessions/${sessionCode}/attempts`, {
    headers: { "X-Student-Token": studentToken },
  });
  attemptsUsed = data.attempts_used;
  maxAttempts = data.max_attempts;
  localStorage.setItem("dealGame.maxAttempts", String(maxAttempts));
  renderAttemptsTable(data.attempts);
  if (data.attempts.length > 0) renderLatest(data.attempts[data.attempts.length - 1]);
  updateAttemptsUi();
  return data;
}

document.getElementById("submit-btn").addEventListener("click", async () => {
  const variables = selectedVariables();
  if (variables.length === 0) return alert("Select at least one variable first.");
  if (!confirm(`Submit attempt ${attemptsUsed + 1} of ${maxAttempts}? Each attempt is scored for real.`)) return;

  const expectedCount = attemptsUsed + 1;
  setFormDisabled(true);
  document.getElementById("pending-banner").hidden = false;

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
      if (data.your_attempts.length > 0) renderLatest(data.your_attempts[data.your_attempts.length - 1]);

      document.getElementById("final-section").hidden = false;
      document.getElementById("final-summary").innerHTML = `
        <dt>Your basic-test rank</dt><dd>${data.your_basic_test_rank ?? "—"}</dd>
        <dt>Your final-test rank</dt><dd>${data.your_final_test_rank ?? "—"}</dd>
      `;
    }
  } catch (err) {
    console.error(err);
  }
}

buildCheckboxes();
refreshAttempts().catch((err) => console.error(err)); // restore state on page load/refresh
const statusHandle = setInterval(pollStatus, 5000);
pollStatus();
