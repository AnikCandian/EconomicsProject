// Landing page: student join, and an admin sign-in toggle. The
// "administrator key" is your real PROFESSOR_API_KEY -- there's no way to
// check it without actually creating a session, so it's stashed locally and
// validated for real the moment "Start session" is clicked on /professor.

const joinView = document.getElementById("join-view");
const adminView = document.getElementById("admin-view");

document.getElementById("open-admin-btn").addEventListener("click", () => {
  joinView.hidden = true;
  adminView.hidden = false;
});

document.getElementById("back-to-join-btn").addEventListener("click", () => {
  adminView.hidden = true;
  joinView.hidden = false;
});

function showError(id, message) {
  const el = document.getElementById(id);
  el.textContent = message;
  el.hidden = false;
}

document.getElementById("join-btn").addEventListener("click", async () => {
  const code = document.getElementById("session-code").value.trim();
  const fullName = document.getElementById("full-name").value.trim();
  document.getElementById("join-error").hidden = true;

  if (!code) return showError("join-error", "Enter the session code your professor shared.");
  if (!fullName) return showError("join-error", "Enter your name so your results can be attributed.");

  try {
    const data = await apiRequest(`/sessions/${code}/join`, {
      method: "POST",
      body: { full_name: fullName },
    });

    localStorage.setItem("dealGame.sessionCode", code);
    localStorage.setItem("dealGame.studentToken", data.student_token);
    localStorage.setItem("dealGame.studentId", data.student_id);
    localStorage.setItem("dealGame.studentName", fullName);
    localStorage.setItem("dealGame.usableColumns", JSON.stringify(data.usable_columns));
    localStorage.setItem("dealGame.categories", JSON.stringify(data.categories));
    localStorage.setItem("dealGame.dummyColumnCategory", JSON.stringify(data.dummy_column_category));

    window.location.href = "/play";
  } catch (err) {
    showError("join-error", err.message);
  }
});

document.getElementById("admin-key").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("admin-signin-btn").click();
});

document.getElementById("admin-signin-btn").addEventListener("click", () => {
  const key = document.getElementById("admin-key").value;
  document.getElementById("admin-error").hidden = true;
  if (!key) return showError("admin-error", "Enter your administrator key.");

  // Not validated here -- there's no "check a key" endpoint. It's stored and
  // used as X-Professor-Key the moment you click "Start session" there.
  sessionStorage.setItem("dealGame.professorKey", key);
  window.location.href = "/professor";
});
