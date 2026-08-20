// Professor page: start a session, poll the dashboard every 5s, stop it.

const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const startSection = document.getElementById("start-section");
const sessionSection = document.getElementById("session-section");
const resultsSection = document.getElementById("results-section");

let sessionCode = null;
let hostToken = null;
let pollHandle = null;

startBtn.addEventListener("click", async () => {
  const key = document.getElementById("professor-key").value;
  const errorEl = document.getElementById("start-error");
  errorEl.textContent = "";

  try {
    const data = await apiRequest("/sessions", {
      method: "POST",
      headers: { "X-Professor-Key": key },
    });
    sessionCode = data.session_code;
    hostToken = data.host_token;

    document.getElementById("session-code").textContent = sessionCode;
    document.getElementById("host-token").textContent = hostToken;
    startSection.hidden = true;
    sessionSection.hidden = false;

    pollDashboard();
    pollHandle = setInterval(pollDashboard, 5000);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

async function pollDashboard() {
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/dashboard`, {
      headers: { "X-Host-Token": hostToken },
    });
    renderDashboard(data);
  } catch (err) {
    document.getElementById("stop-error").textContent = err.message;
  }
}

function renderDashboard(data) {
  document.getElementById("dashboard-summary").innerHTML = `
    <dt>Status</dt><dd>${data.status}</dd>
    <dt>Students online</dt><dd>${data.students_total}</dd>
    <dt>Students finalized</dt><dd>${data.students_finalized}</dd>
    <dt>Average variables chosen</dt><dd>${data.average_variables_chosen.toFixed(2)}</dd>
  `;

  const onlineList = document.getElementById("students-online");
  onlineList.innerHTML = "";
  data.students_online.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.full_name} (${s.student_id})`;
    onlineList.appendChild(li);
  });

  renderLeaderboardTable("#leaderboard-table tbody", data.leaderboard, "basic_test", true);
}

function renderLeaderboardTable(bodySelector, entries, metricKey, includeEquation) {
  const tbody = document.querySelector(bodySelector);
  tbody.innerHTML = "";
  entries.forEach((entry, index) => {
    const metrics = entry[metricKey] || {};
    const row = document.createElement("tr");
    const name = entry.warning
      ? `⚠️ ${entry.full_name} (${entry.student_id})`
      : `${entry.full_name} (${entry.student_id})`;
    if (entry.warning) row.title = entry.warning;
    row.innerHTML = `
      <td>${index + 1}</td>
      <td>${name}</td>
      <td>${entry.variables.join(", ")}</td>
      <td>${fmtPct(metrics.accuracy)}</td>
      <td>${fmtPct(metrics.yes_deal_accuracy)}</td>
      <td>${fmtPct(metrics.no_deal_accuracy)}</td>
      ${includeEquation ? `<td><code>${entry.equation}</code></td>` : ""}
    `;
    tbody.appendChild(row);
  });
}

stopBtn.addEventListener("click", async () => {
  const errorEl = document.getElementById("stop-error");
  errorEl.textContent = "";

  try {
    const data = await apiRequest(`/sessions/${sessionCode}/stop`, {
      method: "POST",
      headers: { "X-Host-Token": hostToken },
    });
    clearInterval(pollHandle);
    resultsSection.hidden = false;
    renderLeaderboardTable("#basic-results-table tbody", data.basic_test_leaderboard, "basic_test", false);
    renderLeaderboardTable("#final-results-table tbody", data.final_test_leaderboard, "final_test", false);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});
