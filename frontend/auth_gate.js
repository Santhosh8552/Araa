(function () {
  "use strict";
  var auth = document.getElementById("auth");
  if (!auth) return;
  var $ = function (id) { return document.getElementById(id); };
  var msg = $("auth_msg");
  var go = $("auth_go");

  var COPY = {
    forgot: {
      title: "Reset password",
      sub: "Enter the email address you signed up with and we'll help you get back into your account."
    }
  };

  function mode() { return auth.getAttribute("data-mode") || "login"; }

  function setMsg(text, kind) {
    if (!msg) return;
    msg.className = "ag-err" + (kind ? " ag-" + kind : "");
    msg.textContent = text || "";
  }

  function clearInvalid() {
    auth.querySelectorAll('[aria-invalid="true"]').forEach(function (el) { el.removeAttribute("aria-invalid"); });
  }

  function fail(el, text) {
    setMsg(text);
    if (el) { el.setAttribute("aria-invalid", "true"); el.focus(); }
    return false;
  }

  function switchMode(next) {
    clearInvalid();
    setMsg("");
    if (next === "forgot") {
      auth.setAttribute("data-mode", "forgot");
      $("authTitle").textContent = COPY.forgot.title;
      $("authSubtitle").textContent = COPY.forgot.sub;
      var fe = $("forgot_email");
      if (fe && !fe.value && $("email")) fe.value = $("email").value;
      if (fe) fe.focus();
      return;
    }
    if (typeof window._applyAuthModeFallback === "function") window._applyAuthModeFallback(next);
    else auth.setAttribute("data-mode", next);
    focusFirst();
  }

  function focusFirst() {
    var order = mode() === "signup" ? ["su_name", "email", "password"] : ["email", "password"];
    for (var i = 0; i < order.length; i++) {
      var el = $(order[i]);
      if (el && !el.value) { el.focus(); return; }
    }
  }

  function strength(pw) {
    if (!pw) return 0;
    var s = 0;
    if (pw.length >= 10) s++;
    if (/[a-z]/i.test(pw) && /\d/.test(pw)) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw) || pw.length >= 14) s++;
    return Math.max(1, s);
  }
  var LABELS = ["", "Weak", "Fair", "Good", "Strong"];

  function updateStrength() {
    var pw = $("password").value;
    var s = strength(pw);
    $("pwStrength").setAttribute("data-s", String(s));
    $("pwStrengthText").textContent = pw ? "Password strength: " + LABELS[s] : "";
  }

  // Validate before app.js's own click handler sends the request.
  function validate() {
    clearInvalid();
    var m = mode();
    var email = $("email"), pw = $("password");
    if (m === "signup") {
      var name = $("su_name");
      if (!name.value.trim()) return fail(name, "Enter your full name.");
      if (!email.value.trim()) return fail(email, "Enter your email address.");
      if (pw.value.length < 10 || !/[a-z]/i.test(pw.value) || !/\d/.test(pw.value))
        return fail(pw, "Use at least 10 characters, with a letter and a number.");
      var pw2 = $("password2");
      if (pw2.value !== pw.value) return fail(pw2, "The passwords don't match.");
      var terms = $("acceptTerms");
      if (!terms.checked) return fail(terms, "Please confirm you understand the trading risk.");
      return true;
    }
    if (!email.value.trim() || !pw.value) return fail(!email.value.trim() ? email : pw, "Enter your email address and password.");
    return true;
  }

  var busyTimer = null;
  function setBusy(on) {
    if (!go) return;
    if (on) {
      go.dataset.label = go.textContent;
      go.textContent = mode() === "signup" ? "Creating account…" : "Signing in…";
      go.setAttribute("aria-busy", "true");
      clearTimeout(busyTimer);
      busyTimer = setTimeout(function () { setBusy(false); }, 20000);
    } else if (go.getAttribute("aria-busy") === "true") {
      go.removeAttribute("aria-busy");
      if (go.dataset.label) go.textContent = go.dataset.label;
      clearTimeout(busyTimer);
    }
  }

  if (go) {
    go.addEventListener("click", function (e) {
      if (go.getAttribute("aria-busy") === "true" || !validate()) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }
      setMsg("");
      setBusy(true);
    }, true);
  }

  // app.js reports errors through #auth_msg and hides #auth on success.
  if (msg && window.MutationObserver) {
    new MutationObserver(function () { if (msg.textContent) setBusy(false); })
      .observe(msg, { childList: true, characterData: true, subtree: true });
  }

  var wasHidden = auth.classList.contains("hide");
  if (window.MutationObserver) {
    new MutationObserver(function () {
      var hidden = auth.classList.contains("hide") || auth.style.display === "none";
      if (hidden) setBusy(false);
      if (wasHidden && !hidden) setTimeout(focusFirst, 60);
      wasHidden = hidden;
    }).observe(auth, { attributes: true, attributeFilter: ["class", "style"] });
  }

  auth.addEventListener("click", function (e) {
    var eye = e.target.closest("[data-eye]");
    if (eye) {
      var input = $(eye.getAttribute("data-eye"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      eye.textContent = show ? "Hide" : "Show";
      eye.setAttribute("aria-pressed", String(show));
      eye.setAttribute("aria-label", show ? "Hide password" : "Show password");
      input.focus();
      return;
    }
    var link = e.target.closest("[data-acct]");
    if (!link) return;
    e.preventDefault();
    var action = link.getAttribute("data-acct");
    if (action === "toggle") switchMode(mode() === "signup" ? "login" : "signup");
    else switchMode(action);
    auth.scrollTo({ top: 0, behavior: "smooth" });
  });

  auth.addEventListener("input", function (e) {
    if (e.target.getAttribute("aria-invalid") === "true") e.target.removeAttribute("aria-invalid");
    if (e.target.id === "password") updateStrength();
  });
  auth.addEventListener("change", function (e) {
    if (e.target.type === "checkbox") e.target.removeAttribute("aria-invalid");
  });

  var forgotGo = $("forgot_go");
  function submitForgot() {
    var fe = $("forgot_email");
    clearInvalid();
    if (!fe.value.trim() || fe.value.indexOf("@") < 1) return fail(fe, "Enter a valid email address.");
    setMsg("Self-service password reset isn't available yet. Please contact Araa support to reset the password for " + fe.value.trim() + ".", "info");
  }
  if (forgotGo) forgotGo.addEventListener("click", submitForgot);
  if ($("forgot_email")) $("forgot_email").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submitForgot(); } });
  if ($("password2")) $("password2").addEventListener("keydown", function (e) { if (e.key === "Enter") go.click(); });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || auth.classList.contains("hide") || auth.style.display === "none") return;
    if (mode() === "forgot") switchMode("login");
    else if (typeof window.closeAuthToLanding === "function") window.closeAuthToLanding();
  });
})();
