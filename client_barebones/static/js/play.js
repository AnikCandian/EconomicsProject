// Student variable-picking page. No live /explore preview any more (that
// endpoint is deprecated -- see API_PROTOCOL.md, "Attempts"): pick
// variables, submit, then poll every second (both GET /attempts and
// GET /status) to confirm what actually landed server-side, rather than
// trusting the POST response alone. Up to 3 attempts per session.
//
// Selecting every category of one one-hot field at once (e.g. all 16
// Industry values) is never sent to the server -- those columns are
// perfectly collinear with the intercept and can't produce a usable
// model. The server enforces the same rule independently and never counts
// it as an attempt; GET /status's last_invalid_selection is how this
// client learns about a rejection if the /finalize response itself was
// lost.

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
let lastSeenInvalidAt = 0; // attempted_at of the last invalid_selection we've already shown

function checkboxLabel(value, labelText) {
  const label = document.createElement("label");
  label.className = "checkbox-option";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = "variables";
  input.value = value;
  input.addEventListener("change", updateInvalidSelectionUi);
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

function setInvalidSelectionBanner(message) {
  const el = document.getElementById("invalid-selection-banner");
  if (message) {
    el.textContent = "⚠️ " + message;
    el.hidden = false;
  } else {
    el.hidden = true;
  }
}

// Live check as boxes are (un)checked -- this is what keeps a full-category
// selection from ever being submitted in the first place (see
// API_PROTOCOL.md, "Attempts", (a)).
function updateInvalidSelectionUi() {
  const culprits = fullySelectedCategories(selectedVariables(), categories);
  setInvalidSelectionBanner(culprits.length > 0 ? oneHotCollinearityMessage(culprits) : "");
}

// A rejection the server logged for us (either the direct /finalize
// response, or discovered via /status polling because that response never
// arrived) -- shown with the exact same banner as the client-side check
// above, since it's the same rule, just caught late.
function handleInvalidSelectionResult(invalid) {
  lastSeenInvalidAt = Math.max(lastSeenInvalidAt, invalid.attempted_at);
  if (confirmPollHandle) {
    clearInterval(confirmPollHandle);
    confirmPollHandle = null;
  }
  document.getElementById("pending-banner").hidden = true;
  setInvalidSelectionBanner(invalid.message);
  if (attemptsUsed < maxAttempts) setFormDisabled(false);
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
      <td>${a.attempt_number}</td>
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

// POST /finalize once. Returns true if the confirm-poll loop below should
// stop (the response itself already told us the outcome), false if the
// caller should keep polling to find out.
async function postFinalize(variables) {
  try {
    const response = await apiRequest(`/sessions/${sessionCode}/finalize`, {
      method: "POST",
      headers: { "X-Student-Token": studentToken },
      body: { variables },
    });
    if (response.status === "invalid_selection") {
      // Shouldn't normally happen since (a) already blocked it -- but
      // handle the direct response too, e.g. if `categories` went stale.
      handleInvalidSelectionResult(response);
      return true;
    }
  } catch (err) {
    if (err.status) {
      // A real HTTP response came back -- the server received this
      // request and rejected it outright (unusable columns, an unfittable
      // design matrix, ...). That's a definitive answer, not a
      // maybe-it-landed network hiccup: none of these cases ever reach
      // Session.finalize()'s attempt-recording step, so nothing was
      // consumed. Show it and stop -- polling/resending would just repeat
      // the identical failure forever (this used to hang the page here).
      setInvalidSelectionBanner(err.message);
      document.getElementById("pending-banner").hidden = true;
      if (attemptsUsed < maxAttempts) setFormDisabled(false);
      return true;
    }
    // A genuine network-level failure (no HTTP response at all) -- the
    // attempt may still have landed server-side, so fall through to
    // polling rather than assuming it didn't.
    console.warn("finalize request failed, confirming via polling instead:", err.message);
  }
  return false;
}

document.getElementById("submit-btn").addEventListener("click", async () => {
  const variables = selectedVariables();
  if (variables.length === 0) return alert("Select at least one variable first.");

  // (a) Never even send a full-category selection -- same rule the server
  // enforces, checked here first so it's blocked before any request goes out.
  const culprits = fullySelectedCategories(variables, categories);
  if (culprits.length > 0) {
    setInvalidSelectionBanner(oneHotCollinearityMessage(culprits));
    return;
  }

  if (!confirm(`Submit attempt ${attemptsUsed + 1} of ${maxAttempts}? Each attempt is scored for real.`)) return;

  const expectedCount = attemptsUsed + 1;
  const submitStartedAt = Date.now() / 1000;
  setFormDisabled(true);
  setInvalidSelectionBanner("");
  document.getElementById("pending-banner").hidden = false;

  if (await postFinalize(variables)) return;

  // Poll every second until either the attempt count reflects the new
  // attempt, or /status reports the submission was rejected as an invalid
  // (full-category, one-hot collinearity) selection -- either way, this is
  // the authoritative source of truth, not the POST response above. (b)
  //
  // If 3 polls in a row show neither -- the original POST may never have
  // reached the server at all, not just its response getting lost -- resend
  // it rather than leaving the student staring at "Submitted..." forever.
  // If it turns out the *original* POST actually did land too (just slowly),
  // this resend creates a genuine second attempt with identical variables --
  // didResend tracks that so the resolve step below can try to collapse it
  // back down to one, via a call the student never sees or triggers directly.
  let ticksSinceLastPost = 0;
  let didResend = false;
  confirmPollHandle = setInterval(async () => {
    try {
      const statusData = await apiRequest(`/sessions/${sessionCode}/status`, {
        headers: { "X-Student-Token": studentToken },
      });
      const invalid = statusData.last_invalid_selection;
      if (invalid && invalid.attempted_at >= submitStartedAt) {
        handleInvalidSelectionResult(invalid);
        return;
      }
      let data = await refreshAttempts();
      if (data.attempts_used >= expectedCount) {
        clearInterval(confirmPollHandle);
        confirmPollHandle = null;
        if (didResend) {
          try {
            const collapsed = await apiRequest(`/sessions/${sessionCode}/attempts/collapse-duplicate`, {
              method: "POST",
              headers: { "X-Student-Token": studentToken },
            });
            if (collapsed.status === "withdrawn") data = await refreshAttempts();
          } catch (err) {
            console.error("collapse-duplicate failed:", err);
          }
        }
        document.getElementById("pending-banner").hidden = true;
        if (data.attempts_remaining > 0) setFormDisabled(false);
        return;
      }
      ticksSinceLastPost += 1;
      if (ticksSinceLastPost >= 3) {
        ticksSinceLastPost = 0;
        didResend = true;
        if (await postFinalize(variables)) {
          clearInterval(confirmPollHandle);
          confirmPollHandle = null;
        }
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
    if (data.last_invalid_selection && data.last_invalid_selection.attempted_at > lastSeenInvalidAt) {
      handleInvalidSelectionResult(data.last_invalid_selection);
    }
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
