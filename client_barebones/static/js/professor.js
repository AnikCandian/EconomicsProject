// Professor page: start a session, poll the dashboard every 5s, stop it.

const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const startSection = document.getElementById("start-section");
const sessionSection = document.getElementById("session-section");
const resultsSection = document.getElementById("results-section");

let sessionCode = null;
let hostToken = null;
let pollHandle = null;
let defaultSeasonSplit = null; // {train, basicTest, finalTest} -- populated from GET /seasons

loadSeasonPicker();

startBtn.addEventListener("click", async () => {
  const key = document.getElementById("professor-key").value;
  const errorEl = document.getElementById("start-error");
  errorEl.textContent = "";

  const body = {
    train_seasons: checkedSeasons("season-check--train"),
    basic_test_seasons: checkedSeasons("season-check--basic"),
    final_test_seasons: checkedSeasons("season-check--final"),
  };

  try {
    const data = await apiRequest("/sessions", {
      method: "POST",
      headers: { "X-Professor-Key": key },
      body,
    });
    sessionCode = data.session_code;
    hostToken = data.host_token;

    document.getElementById("session-code").textContent = sessionCode;
    document.getElementById("host-token").textContent = hostToken;
    renderSeasonInfo(data);
    startSection.hidden = true;
    sessionSection.hidden = false;

    pollDashboard();
    pollHandle = setInterval(pollDashboard, 5000);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---- season picker (pre-session only -- fixed once a session starts) ----

async function loadSeasonPicker() {
  try {
    const data = await apiRequest("/seasons");
    defaultSeasonSplit = {
      train: data.default_train_seasons,
      basicTest: data.default_basic_test_seasons,
      finalTest: data.default_final_test_seasons,
    };
    buildSeasonTable(data.available_seasons, defaultSeasonSplit);
  } catch (err) {
    document.querySelector("#season-table tbody").innerHTML =
      `<tr><td colspan="4">Couldn't load seasons: ${err.message}</td></tr>`;
  }
}

function buildSeasonTable(availableSeasons, split) {
  const tbody = document.querySelector("#season-table tbody");
  tbody.innerHTML = "";
  availableSeasons.forEach((season) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>Season ${season}</td>
      <td><input type="checkbox" class="season-check--train" value="${season}" ${split.train.includes(season) ? "checked" : ""}></td>
      <td><input type="checkbox" class="season-check--basic" value="${season}" ${split.basicTest.includes(season) ? "checked" : ""}></td>
      <td><input type="checkbox" class="season-check--final" value="${season}" ${split.finalTest.includes(season) ? "checked" : ""}></td>
    `;
    tbody.appendChild(row);
  });
}

document.getElementById("season-reset-btn").addEventListener("click", () => {
  const seasons = Array.from(document.querySelectorAll("#season-table tbody tr")).map((row) =>
    Number(row.querySelector("td").textContent.replace("Season ", ""))
  );
  if (defaultSeasonSplit) buildSeasonTable(seasons, defaultSeasonSplit);
});

function checkedSeasons(className) {
  return Array.from(document.querySelectorAll(`.${className}:checked`)).map((el) => Number(el.value));
}

function formatSeasonRanges(seasons) {
  if (!seasons || seasons.length === 0) return "none";
  const sorted = [...seasons].sort((a, b) => a - b);
  const ranges = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i <= sorted.length; i++) {
    const cur = sorted[i];
    if (cur === prev + 1) {
      prev = cur;
      continue;
    }
    ranges.push(start === prev ? `${start}` : `${start}–${prev}`);
    if (i < sorted.length) {
      start = prev = cur;
    }
  }
  return ranges.join(", ");
}

function renderSeasonInfo(data) {
  document.getElementById("session-season-info").textContent =
    `Train: seasons ${formatSeasonRanges(data.train_seasons)} · ` +
    `Basic test (live): seasons ${formatSeasonRanges(data.basic_test_seasons)} · ` +
    `Final test (revealed at stop): seasons ${formatSeasonRanges(data.final_test_seasons)}`;
  document.getElementById("final-basic-heading").textContent =
    `Leaderboard — seasons ${formatSeasonRanges(data.basic_test_seasons)} (basic test)`;
  document.getElementById("final-final-heading").textContent =
    `Leaderboard — seasons ${formatSeasonRanges(data.final_test_seasons)} (final test)`;
}

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
    const name = `${entry.full_name} (${entry.student_id}) · best of attempt ${entry.attempt_number}`;
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
