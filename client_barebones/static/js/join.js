// Student join page: exchange a session code + name for a student token,
// stash it in localStorage, and hand off to the variable-picking page.

document.getElementById("join-btn").addEventListener("click", async () => {
  const code = document.getElementById("session-code").value.trim();
  const fullName = document.getElementById("full-name").value.trim();
  const errorEl = document.getElementById("join-error");
  errorEl.textContent = "";

  try {
    const data = await apiRequest(`/sessions/${code}/join`, {
      method: "POST",
      body: { full_name: fullName },
    });

    localStorage.setItem("dealGame.sessionCode", code);
    localStorage.setItem("dealGame.studentToken", data.student_token);
    localStorage.setItem("dealGame.studentId", data.student_id);
    localStorage.setItem("dealGame.usableColumns", JSON.stringify(data.usable_columns));
    localStorage.setItem("dealGame.categories", JSON.stringify(data.categories));
    localStorage.setItem("dealGame.dummyColumnCategory", JSON.stringify(data.dummy_column_category));
    localStorage.setItem("dealGame.maxAttempts", String(data.max_attempts));

    window.location.href = "/play";
  } catch (err) {
    errorEl.textContent = err.message;
  }
});
