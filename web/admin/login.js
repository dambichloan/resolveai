(function () {
  var form = document.getElementById("loginForm"), error = document.getElementById("error"), button = form.querySelector("button");
  fetch("/api/admin/me", { credentials: "same-origin" }).then(function (r) { if (r.ok) location.replace("/admin/"); });
  form.addEventListener("submit", function (event) {
    event.preventDefault(); error.hidden = true; button.disabled = true;
    fetch("/api/admin/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: document.getElementById("username").value, password: document.getElementById("password").value }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (body) { if (!r.ok) throw new Error((body.error && body.error.message) || "Không thể đăng nhập."); }); })
      .then(function () { location.replace("/admin/"); })
      .catch(function (e) { error.textContent = e.message; error.hidden = false; button.disabled = false; });
  });
})();
