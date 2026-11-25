// Widget chatbot Savani. Nhúng vào bất kỳ trang nào bằng 1 dòng:
//   <script src="https://<máy-chủ-chat>/widget/chatbot.js" defer></script>
// API mặc định lấy theo máy chủ đã tải file này (đổi bằng data-api="https://..."). Nội dung chỉ gắn bằng textContent (chống XSS).
(function () {
  "use strict";
  if (window.SavaniChat) return;
  var me = document.currentScript, API = "";
  if (me) {
    API = (me.getAttribute("data-api") || "").replace(/\/$/, "");
    if (!API && me.src) { try { API = new URL(me.src).origin; } catch (e) {} }
    if (!document.querySelector('link[href*="chatbot.css"]') && me.src) {
      var l = document.createElement("link"); l.rel = "stylesheet"; l.href = me.src.replace(/chatbot\.js.*$/, "chatbot.css"); document.head.appendChild(l);
    }
  }
  var FILE_MODE = location.protocol === "file:";
  var STATUS_TEXT = { AI_Handling: "Trợ lý Savani", Waiting_Agent: "Đang chờ nhân viên", Agent_Handling: "Nhân viên đang hỗ trợ", Closed: "Đã kết thúc" };
  var ROLE_NAME = { ai: "Trợ lý Savani", staff: "Nhân viên CSKH" };
  var CHIPS = [
    { text: "Tư vấn size giúp mình" },
    { text: "Chính sách đổi hàng", action: "policy_return" },
    { text: "Chính sách bảo hành", action: "policy_warranty" },
    { text: "Tra cứu đơn hàng" },
    { text: "Gặp nhân viên", action: "request_handoff" }
  ];
  var BOT = '<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="23" fill="#fff"/><path d="M24 7v5" stroke="#d4141c" stroke-width="3" stroke-linecap="round"/><circle cx="24" cy="6" r="3" fill="#d4141c"/><rect x="9" y="12" width="30" height="24" rx="10" fill="#141414"/><circle cx="18" cy="23" r="3.4" fill="#fff"/><circle cx="30" cy="23" r="3.4" fill="#fff"/><path d="M18 30c2 2.2 10 2.2 12 0" stroke="#d4141c" stroke-width="2.6" fill="none" stroke-linecap="round"/><rect x="5" y="19" width="4" height="9" rx="2" fill="#d4141c"/><rect x="39" y="19" width="4" height="9" rx="2" fill="#d4141c"/></svg>';

  var sid = null, token = null, lastId = 0, sending = false, poll = null, shown = {}, chatStarted = false;
  function store(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function uuid() { return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  // ---------- dựng giao diện
  var root = el("div", "svc"), fab = el("button", "svc-fab"), panel = el("section", "svc-panel");
  fab.type = "button"; fab.setAttribute("aria-label", "Mở chat tư vấn Savani"); fab.innerHTML = BOT; fab.appendChild(el("span", "dot"));
  var tip = el("div", "svc-tip", "Cần tư vấn size, đổi trả hay tra đơn? Chat với mình nhé!");
  var tipX = el("button", null, "×"); tipX.type = "button"; tipX.setAttribute("aria-label", "Đóng gợi ý"); tip.appendChild(tipX);
  panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Chat với trợ lý Savani");
  var head = el("div", "svc-head"), hb = el("div"), statusEl = el("span", "svc-status"), closeBtn = el("button", "x", "×");
  head.insertAdjacentHTML("beforeend", BOT); hb.appendChild(el("b", null, "Trợ lý Savani")); hb.appendChild(statusEl); head.appendChild(hb);
  closeBtn.type = "button"; closeBtn.setAttribute("aria-label", "Thu nhỏ chat"); head.appendChild(closeBtn);
  var note = el("p", "svc-note", "Cuộc trò chuyện được lưu để hỗ trợ bạn. Vui lòng không gửi mật khẩu hay số thẻ ngân hàng.");
  var log = el("div", "svc-log"); log.setAttribute("role", "log"); log.setAttribute("aria-live", "polite");
  var chips = el("div", "svc-chips");
  var banner = el("div", "svc-banner"); banner.hidden = true;
  var form = el("form", "svc-form"), input = el("input"), sendBtn = el("button", null, "Gửi");
  input.type = "text"; input.maxLength = 1000; input.placeholder = "Nhập tin nhắn..."; input.setAttribute("aria-label", "Tin nhắn"); input.autocomplete = "off";
  sendBtn.type = "submit"; form.appendChild(input); form.appendChild(sendBtn);
  var finish = el("button", "svc-finish", "Kết thúc cuộc trò chuyện"); finish.type = "button"; finish.hidden = true;
  var restart = el("button", "svc-restart", "Bắt đầu cuộc trò chuyện mới"); restart.type = "button"; restart.hidden = true;
  [head, note, log, chips, banner, form, finish, restart].forEach(function (n) { panel.appendChild(n); });
  root.appendChild(panel); root.appendChild(tip); root.appendChild(fab);
  CHIPS.forEach(function (c) { var b = el("button", null, c.text); b.type = "button"; b.addEventListener("click", function () { send(c.text, c.action); }); chips.appendChild(b); });

  function showBanner(t) { banner.textContent = t; banner.hidden = !t; }
  function scroll() { log.scrollTop = log.scrollHeight; }

  // ---------- hiển thị tin nhắn
  function bubble(m) {
    var d = el("div", "svc-msg " + m.role);
    if (ROLE_NAME[m.role]) d.appendChild(el("span", "svc-who", ROLE_NAME[m.role]));
    d.appendChild(document.createTextNode(m.text));
    if (m.ui && m.ui.type === "ticket_summary") d.appendChild(summaryCard(m));
    if (m.ui && m.ui.type === "ticket_created") d.appendChild(el("span", "svc-badge", "Mã yêu cầu: " + m.ui.code));
    if (m.ui && m.ui.type === "handoff_notice") d.appendChild(el("span", "svc-badge", "Đã chuyển cho nhân viên"));
    log.appendChild(d); scroll(); return d;
  }
  function renderMessage(m) { if (shown[m.id]) return; shown[m.id] = true; lastId = Math.max(lastId, m.id); return bubble(m); }
  function summaryCard(m) {
    var card = el("div", "svc-card"), dl = el("dl");
    dl.appendChild(el("dt", null, "Loại")); dl.appendChild(el("dd", null, m.ui.ticket_type || ""));
    (m.ui.fields || []).forEach(function (f) { dl.appendChild(el("dt", null, f.label)); dl.appendChild(el("dd", null, f.value)); });
    var btns = el("div", "svc-btns"), ok = el("button", null, "Xác nhận"), no = el("button", "alt", "Chỉnh sửa");
    ok.type = no.type = "button";
    function lock() { ok.disabled = no.disabled = true; }
    ok.addEventListener("click", function () { lock(); send("", "confirm_ticket"); });
    no.addEventListener("click", function () { lock(); send("", "reject_ticket"); });
    btns.appendChild(ok); btns.appendChild(no); card.appendChild(dl); card.appendChild(btns); return card;
  }

  // ---------- trạng thái + gọi API
  function applyStatus(s) {
    statusEl.textContent = STATUS_TEXT[s] || s;
    var closed = s === "Closed"; input.disabled = sendBtn.disabled = closed;
    restart.hidden = !closed;
    finish.hidden = closed || s !== "AI_Handling" || !sid;
    if (s === "Waiting_Agent" || s === "Agent_Handling") startPoll(); else stopPoll();
  }
  function startPoll() { if (!poll) poll = setInterval(fetchNew, 3000); }
  function stopPoll() { if (poll) { clearInterval(poll); poll = null; } }
  function apply(d) {
    if (d.session_token) { token = d.session_token; store("sv_token", token); }
    if (d.session_id) { sid = d.session_id; store("sv_sid", sid); }
    (d.messages || []).forEach(renderMessage); applyStatus(d.status);
  }
  function errText(res, body) {
    var e = (body && body.error) || {};
    if (res.status === 429) return e.message || "Bạn gửi quá nhanh, vui lòng đợi một chút.";
    return e.message || "Có lỗi xảy ra (mã " + res.status + "), vui lòng thử lại.";
  }
  function offlineText() {
    if (FILE_MODE) return "Trang đang mở trực tiếp từ file nên không gọi được máy chủ. Hãy mở qua địa chỉ http://localhost:8000";
    return "Không kết nối được máy chủ chat" + (API ? " (" + API + ")" : "") + ". Hãy kiểm tra máy chủ đang chạy rồi thử lại.";
  }
  function send(text, action) {
    if (sending) return; sending = true; showBanner(""); chips.hidden = true; chatStarted = true;
    var pending = text ? bubble({ role: "customer", text: text }) : null, typing = el("div", "svc-typing", "Trợ lý đang trả lời...");
    log.appendChild(typing); scroll();
    function cleanup() { if (pending && pending.parentNode) pending.parentNode.removeChild(pending); pending = null; if (typing.parentNode) typing.parentNode.removeChild(typing); }
    fetch(API + "/api/chat/messages", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Session-Token": token || "" },
      body: JSON.stringify({ session_id: sid, text: text || null, client_msg_id: uuid(), action: action || null })
    }).then(function (res) { return res.json().catch(function () { return {}; }).then(function (body) { return { res: res, body: body }; }); })
      .then(function (r) {
        cleanup();
        if (r.res.ok) { apply(r.body); return; }
        if (r.res.status === 403) { showBanner("Phiên không còn hợp lệ. Đang bắt đầu lại."); reset(true); return; }
        if (r.res.status === 409 && r.body.error && r.body.error.code === "session_closed") applyStatus("Closed");
        showBanner(errText(r.res, r.body));
      }).catch(function () { cleanup(); showBanner(offlineText()); })
      .then(function () { sending = false; });
  }
  function fetchNew() {
    if (!sid) return;
    fetch(API + "/api/chat/sessions/" + encodeURIComponent(sid) + "/messages?after=" + lastId, { headers: { "X-Session-Token": token || "" } })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { if (d) apply(d); }).catch(function () {});
  }
  function greet() {
    bubble({ role: "ai", text: "Xin chào, mình là trợ lý CSKH của Savani. Mình có thể tư vấn size, chính sách đổi trả, tra cứu đơn hàng và ghi nhận yêu cầu của bạn." });
    chips.hidden = false;
  }
  function reset(keepBanner) {
    stopPoll(); sid = token = null; lastId = 0; shown = {}; chatStarted = false; store("sv_sid", null); store("sv_token", null);
    log.textContent = ""; if (!keepBanner) showBanner(""); applyStatus("AI_Handling"); greet();
  }

  // ---------- mở/đóng
  function open(text) {
    panel.hidden = false; tip.hidden = true; store("sv_open", "1"); fab.setAttribute("aria-expanded", "true");
    if (fab.querySelector(".dot")) fab.querySelector(".dot").hidden = true;
    if (text) send(text); else setTimeout(function () { input.focus(); }, 0);
  }
  function close() { panel.hidden = true; store("sv_open", null); fab.setAttribute("aria-expanded", "false"); fab.focus(); }
  fab.addEventListener("click", function () { panel.hidden ? open() : close(); });
  closeBtn.addEventListener("click", close);
  tipX.addEventListener("click", function () { tip.hidden = true; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) close(); });
  form.addEventListener("submit", function (e) { e.preventDefault(); var t = input.value.trim(); if (!t) return; input.value = ""; send(t); });
  finish.addEventListener("click", function () {
    if (!sid || sending) return;
    sending = true; showBanner("");
    fetch(API + "/api/chat/sessions/" + encodeURIComponent(sid) + "/close", {
      method: "POST", headers: { "X-Session-Token": token || "" }
    }).then(function (res) { return res.json().catch(function () { return {}; }).then(function (body) { return { res: res, body: body }; }); })
      .then(function (r) {
        if (r.res.ok) { applyStatus(r.body.status); return; }
        showBanner(errText(r.res, r.body));
      }).catch(function () { showBanner(offlineText()); })
      .then(function () { sending = false; });
  });
  restart.addEventListener("click", function () { reset(false); });

  function boot() {
    document.body.appendChild(root); tip.hidden = true; setTimeout(function () { if (panel.hidden) tip.hidden = false; }, 3500);
    sid = load("sv_sid"); token = load("sv_token"); applyStatus("AI_Handling");
    if (sid && token) {   // tải lại trang: dựng lại lời chào rồi nạp lịch sử từ máy chủ
      greet();
      fetch(API + "/api/chat/sessions/" + encodeURIComponent(sid) + "/messages?after=0", { headers: { "X-Session-Token": token } })
        .then(function (r) { return r.status === 403 ? Promise.reject("gone") : r.ok ? r.json() : Promise.reject("err"); })
        .then(function (d) { chips.hidden = d.messages.length > 0; apply(d); })
        .catch(function (why) {
          if (why === "gone") { reset(true); showBanner("Cuộc trò chuyện trước đó không còn trên máy chủ nên đã bắt đầu lại."); }
          else showBanner(offlineText());
        });
      if (load("sv_open") === "1") open();
    } else greet();
  }
  window.SavaniChat = { open: open, close: close };
  if (document.body) boot(); else document.addEventListener("DOMContentLoaded", boot);
})();
