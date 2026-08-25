// Monitoring page. Starts/stops a real session, polls the real dashboard
// every 5s, and computes "Most-included predictors" / "Accuracy
// distribution" client-side from the real leaderboard data returned each
// poll -- there's no persistence across sessions, so unlike the original
// mockup there's no fabricated 30-day history here; "Final results" is
// populated for real once the session is actually stopped.

const professorKey = sessionStorage.getItem("dealGame.professorKey");
if (!professorKey) {
  window.location.href = "/";
}

document.getElementById("signout-btn").addEventListener("click", () => {
  sessionStorage.clear();
  window.location.href = "/";
});

let sessionCode = sessionStorage.getItem("dealGame.hostSessionCode");
let hostToken = sessionStorage.getItem("dealGame.hostToken");
let startedAtMs = Number(sessionStorage.getItem("dealGame.startedAtMs")) || null;
let endedAtMs = Number(sessionStorage.getItem("dealGame.endedAtMs")) || null;
let dashboardHandle = null;
let clockHandle = null;
let defaultSeasonSplit = null; // {train, basicTest, finalTest} -- populated from GET /seasons

function showDashboard() {
  document.getElementById("pre-session").hidden = true;
  document.getElementById("dashboard").hidden = false;
  document.getElementById("session-code-chip").textContent = sessionCode;
}

if (sessionCode && hostToken) {
  showDashboard();
  startPolling();
  startClock();
  if (endedAtMs) renderStoppedState();
} else {
  loadSeasonPicker();
}

document.getElementById("start-btn").addEventListener("click", async () => {
  document.getElementById("start-error").hidden = true;
  const body = {
    train_seasons: checkedSeasons("season-check--train"),
    basic_test_seasons: checkedSeasons("season-check--basic"),
    final_test_seasons: checkedSeasons("season-check--final"),
  };
  try {
    const data = await apiRequest("/sessions", {
      method: "POST",
      headers: { "X-Professor-Key": professorKey },
      body,
    });
    sessionCode = data.session_code;
    hostToken = data.host_token;
    startedAtMs = Date.now();
    sessionStorage.setItem("dealGame.hostSessionCode", sessionCode);
    sessionStorage.setItem("dealGame.hostToken", hostToken);
    sessionStorage.setItem("dealGame.startedAtMs", String(startedAtMs));

    renderSeasonInfo(data);
    showDashboard();
    startPolling();
    startClock();
  } catch (err) {
    const el = document.getElementById("start-error");
    el.textContent = err.message;
    el.hidden = false;
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
    document.getElementById("season-table-body").innerHTML =
      `<tr><td colspan="4" class="empty-note">Couldn't load seasons: ${err.message}</td></tr>`;
  }
}

function buildSeasonTable(availableSeasons, split) {
  const tbody = document.getElementById("season-table-body");
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
  const seasons = Array.from(document.querySelectorAll("#season-table-body tr")).map((row) =>
    Number(row.querySelector("td").textContent.replace("Season ", ""))
  );
  if (defaultSeasonSplit) buildSeasonTable(seasons, defaultSeasonSplit);
});

function checkedSeasons(className) {
  return Array.from(document.querySelectorAll(`.${className}:checked`)).map((el) => Number(el.value));
}

// ---- season-info chips (dashboard, live + final) ----

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
  document.getElementById("season-info-chips").innerHTML = `
    <span class="tag">Train · seasons ${formatSeasonRanges(data.train_seasons)}</span>
    <span class="tag tag-accent">Basic test (live) · seasons ${formatSeasonRanges(data.basic_test_seasons)}</span>
    <span class="tag">Final test (revealed at stop) · seasons ${formatSeasonRanges(data.final_test_seasons)}</span>
  `;
  document.getElementById("final-basic-heading").textContent =
    `Leaderboard — seasons ${formatSeasonRanges(data.basic_test_seasons)} (basic test)`;
  document.getElementById("final-final-heading").textContent =
    `Leaderboard — seasons ${formatSeasonRanges(data.final_test_seasons)} (final test)`;
}

document.getElementById("stop-btn").addEventListener("click", async () => {
  if (!confirm("End this session? Students will no longer be able to explore or finalize.")) return;
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/stop`, {
      method: "POST",
      headers: { "X-Host-Token": hostToken },
    });
    endedAtMs = Date.now();
    sessionStorage.setItem("dealGame.endedAtMs", String(endedAtMs));
    renderFinalResults(data);
    renderStoppedState();
    clearInterval(dashboardHandle);
    clearInterval(clockHandle);
  } catch (err) {
    alert(err.message);
  }
});

function renderStoppedState() {
  document.getElementById("session-bar").className = "session-bar is-idle";
  document.getElementById("session-dot").className = "session-dot";
  document.getElementById("session-title").textContent = "Session ended";
  document.getElementById("session-note").textContent = "Results kept below under Final results.";
  document.getElementById("stop-btn").disabled = true;
  document.getElementById("stop-btn").textContent = "Session ended";
  setTab("final");
}

function startClock() {
  clockHandle = setInterval(() => {
    const end = endedAtMs || Date.now();
    const secs = Math.max(0, Math.floor((end - startedAtMs) / 1000));
    const mm = String(Math.floor(secs / 60)).padStart(2, "0");
    const ss = String(secs % 60).padStart(2, "0");
    document.getElementById("session-elapsed").textContent = `${mm}:${ss}`;
  }, 1000);
}

// ---- tabs ----

function setTab(which) {
  const isLive = which === "live";
  document.getElementById("tab-live-btn").classList.toggle("is-active", isLive);
  document.getElementById("tab-final-btn").classList.toggle("is-active", !isLive);
  document.getElementById("live-panel").hidden = !isLive;
  document.getElementById("final-panel").hidden = isLive;
}
document.getElementById("tab-live-btn").addEventListener("click", () => setTab("live"));
document.getElementById("tab-final-btn").addEventListener("click", () => setTab("final"));

// ---- live dashboard polling ----

function startPolling() {
  pollDashboard();
  dashboardHandle = setInterval(pollDashboard, 5000);
}

async function pollDashboard() {
  try {
    const data = await apiRequest(`/sessions/${sessionCode}/dashboard`, {
      headers: { "X-Host-Token": hostToken },
    });
    renderDashboard(data);
  } catch (err) {
    console.error(err);
  }
}

function renderDashboard(data) {
  renderSeasonInfo(data);

  document.getElementById("session-note").textContent =
    data.students_total + " connected · " + data.students_finalized + " finalized";

  document.getElementById("stat-online").textContent = data.students_total;
  document.getElementById("stat-finalized").textContent = data.students_finalized;
  document.getElementById("stat-avg-vars").textContent = data.average_variables_chosen.toFixed(1);

  const accuracies = data.leaderboard.map((s) => s.basic_test.accuracy);
  document.getElementById("stat-median").textContent = accuracies.length ? (median(accuracies) * 100).toFixed(1) : "—";

  renderLeaderboardRows("leaderboard-rows", data.leaderboard, "basic_test", true);
  renderPopular(data.leaderboard);
  renderDistribution(accuracies);
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function renderLeaderboardRows(containerId, entries, metricKey, showTime) {
  const sorted = [...entries].sort((a, b) => (b[metricKey]?.accuracy ?? 0) - (a[metricKey]?.accuracy ?? 0));
  const container = document.getElementById(containerId);
  container.innerHTML = "";

  if (sorted.length === 0) {
    container.innerHTML = '<p class="empty-note">No finalized submissions yet.</p>';
    return;
  }

  sorted.forEach((entry) => {
    const metrics = entry[metricKey] || {};
    const row = document.createElement("div");
    row.className = "mon-row";
    row.innerHTML = `
      <div class="mon-row__user">
        <div class="mon-avatar">${initials(entry.full_name)}</div>
        <div style="min-width:0">
          <div class="mon-row__name">${entry.full_name}</div>
          <div class="mon-row__spec">best of attempt ${entry.attempt_number} · ${entry.variables.join(", ")}</div>
        </div>
      </div>
      <div class="mon-row__score">${fmtPct(metrics.accuracy)}</div>
      <div class="mon-row__count">${entry.variables.length}</div>
      <div class="mon-row__time">${showTime ? timeAgo(entry.finalized_at) : ""}</div>
    `;
    container.appendChild(row);
  });
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).map((w) => w[0].toUpperCase()).slice(0, 2).join("");
}

function timeAgo(unixSeconds) {
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - unixSeconds));
  if (secs < 60) return secs + "s ago";
  if (secs < 3600) return Math.floor(secs / 60) + "m ago";
  return Math.floor(secs / 3600) + "h ago";
}

function renderPopular(leaderboard) {
  const counts = {};
  leaderboard.forEach((entry) => entry.variables.forEach((v) => (counts[v] = (counts[v] || 0) + 1)));
  const total = leaderboard.length || 1;
  const ranked = Object.entries(counts)
    .map(([label, count]) => ({ label, pct: Math.round((count / total) * 100) }))
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 8);

  const container = document.getElementById("popular-list");
  container.innerHTML = "";
  if (ranked.length === 0) {
    container.innerHTML = '<p class="empty-note">No finalized submissions yet.</p>';
    return;
  }
  ranked.forEach(({ label, pct }) => {
    const row = document.createElement("div");
    row.className = "popular-row";
    row.innerHTML = `
      <div>
        <div class="popular-row__label">${label}</div>
        <div class="popular-bar-track"><div class="popular-bar-fill" style="width:${pct}%"></div></div>
      </div>
      <div class="popular-row__pct">${pct}%</div>
    `;
    container.appendChild(row);
  });
}

function renderDistribution(accuracies) {
  const chart = document.getElementById("dist-chart");
  const labels = document.getElementById("dist-labels");
  chart.innerHTML = "";
  labels.innerHTML = "";

  if (accuracies.length === 0) {
    chart.innerHTML = '<p class="empty-note">No finalized submissions yet.</p>';
    return;
  }

  const bins = [45, 50, 55, 60, 65, 70, 75, 80, 100];
  const counts = new Array(bins.length - 1).fill(0);
  accuracies.forEach((a) => {
    const pct = a * 100;
    for (let i = 0; i < bins.length - 1; i++) {
      if (pct >= bins[i] && pct < bins[i + 1]) { counts[i]++; break; }
      if (i === bins.length - 2 && pct >= bins[i + 1]) counts[i]++;
    }
  });
  const max = Math.max(1, ...counts);

  counts.forEach((n, i) => {
    const col = document.createElement("div");
    col.className = "dist-bar-col";
    const heightPct = Math.round((n / max) * 100);
    col.innerHTML = `<div class="dist-bar-n">${n}</div><div class="dist-bar-fill" style="height:${heightPct}%"></div>`;
    chart.appendChild(col);

    const label = document.createElement("div");
    label.textContent = bins[i] + (i === bins.length - 2 ? "+" : "–" + bins[i + 1]);
    labels.appendChild(label);
  });
}

function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

// ---- final results (after stop) ----

function renderFinalResults(data) {
  document.getElementById("final-empty").hidden = true;
  document.getElementById("final-tables").hidden = false;
  renderLeaderboardRows("final-basic-rows", data.basic_test_leaderboard, "basic_test", false);
  renderLeaderboardRows("final-final-rows", data.final_test_leaderboard, "final_test", false);
}
