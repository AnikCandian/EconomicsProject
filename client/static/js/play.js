// Student variable-picking page: renders checkboxes from what /join
// returned, then explore/finalize/status all talk directly to the API.

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
  document.getElementById("explore-btn").disabled = disabled;
  document.getElementById("finalize-btn").disabled = disabled;
}

function renderResult(data) {
  document.getElementById("result-raw").textContent = JSON.stringify(data, null, 2);
  document.getElementById("result-equation").textContent = data.equation || "";

  const warningEl = document.getElementById("result-warning");
  if (data.warning) {
    warningEl.textContent = "⚠️ " + data.warning;
    warningEl.hidden = false;
  } else {
    warningEl.hidden = true;
  }

  const metrics = data.basic_test || {};
  document.getElementById("result-summary").innerHTML = `
    <dt>Status</dt><dd>${data.status}</dd>
    <dt>Variables</dt><dd>${(data.variables || []).join(", ") || "—"}</dd>
    <dt>Basic test accuracy</dt><dd>${fmtPct(metrics.accuracy)}</dd>
    <dt>Yes-deal accuracy</dt><dd>${fmtPct(metrics.yes_deal_accuracy)}</dd>
    <dt>No-deal accuracy</dt><dd>${fmtPct(metrics.no_deal_accuracy)}</dd>
    <dt>Sample size</dt><dd>${metrics.sample_size ?? "—"}</dd>
  `;

  if (data.status === "already_submitted") {
    document.getElementById("submitted-banner").hidden = false;
    setFormDisabled(true);
  }
}

document.getElementById("explore-btn").addEventListener("click", async () => {
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/explore`, {
      method: "POST",
      headers: { "X-Student-Token": studentToken },
      body: { variables: selectedVariables() },
    });
    renderResult(data);
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("finalize-btn").addEventListener("click", async () => {
  if (!confirm("Finalize this selection? This is one-shot -- you can't change it afterward.")) return;
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/finalize`, {
      method: "POST",
      headers: { "X-Student-Token": studentToken },
      body: { variables: selectedVariables() },
    });
    renderResult(data);
  } catch (err) {
    alert(err.message);
  }
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

      document.getElementById("final-section").hidden = false;
      document.getElementById("final-summary").innerHTML = `
        <dt>Your basic-test rank</dt><dd>${data.your_basic_test_rank ?? "—"}</dd>
        <dt>Your final-test rank</dt><dd>${data.your_final_test_rank ?? "—"}</dd>
      `;
      if (data.your_submission) {
        renderResult({ status: "closed", ...data.your_submission });
      }
    }
  } catch (err) {
    console.error(err);
  }
}

buildCheckboxes();
const statusHandle = setInterval(pollStatus, 5000);
pollStatus();
