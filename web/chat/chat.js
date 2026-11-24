// Mọi nội dung người dùng/AI đều gắn bằng textContent (chống XSS, NFR-SEC-01). Không dùng innerHTML.
(function () {
  "use strict";
  var log = document.getElementById("log"), form = document.getElementById("form"),
      input = document.getElementById("input"), sendBtn = document.getElementById("send"),
      banner = document.getElementById("banner"), statusEl = document.getElementById("status"),
      restart = document.getElementById("restart"), chips = document.getElementById("chips"),
      closeBtn = document.getElementById("close");
  var QUICK = ["Tư vấn size", "Chính sách đổi trả", "Chính sách bảo hành", "Tra cứu đơn hàng", "Gặp nhân viên"];
  if (/[?&]embed=1/.test(location.search)) {
    document.body.classList.add("embed"); closeBtn.hidden = false;
    closeBtn.addEventListener("click", function () { parent.postMessage("svn:close", "*"); });
  }
  var STATUS_TEXT = { AI_Handling: "Trợ lý AI", Waiting_Agent: "Đang chờ nhân viên", Agent_Handling: "Nhân viên đang hỗ trợ", Closed: "Đã kết thúc" };
  var ROLE_NAME = { ai: "Trợ lý Savani", staff: "Nhân viên CSKH" };
  var sid = null, token = null, status = "AI_Handling", lastId = 0, sending = false, poll = null;
  var shown = {};

  function store(k, v) { try { v === null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch (e) {} }
  function load(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function uuid() { return (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  function renderChips() {
    chips.textContent = "";
    QUICK.forEach(function (q) {
      var b = el("button", null, q); b.type = "button";
      var action = ({ "Chính sách đổi trả": "policy_return", "Chính sách bảo hành": "policy_warranty", "Gặp nhân viên": "request_handoff" })[q] || null;
      b.addEventListener("click", function () { if (!sending && !input.disabled) send(q, action); });
      chips.appendChild(b);
    });
  }
  renderChips();

  function showBanner(t) { banner.textContent = t; banner.hidden = !t; }

  function renderMessage(m) {
    if (shown[m.id]) return; shown[m.id] = true; lastId = Math.max(lastId, m.id);
    return bubble(m);
  }
  function bubble(m) {
    var d = el("div", "msg " + m.role);
    if (ROLE_NAME[m.role]) d.appendChild(el("span", "who", ROLE_NAME[m.role]));
    d.appendChild(document.createTextNode(m.text));
    if (m.sources && m.sources.length) {
      var s = (m.sources.map(function (x) { return x.title + (x.section ? " - " + x.section : ""); })).join("; ");
      d.appendChild(el("span", "src", "Nguồn: " + s));
    }
    if (m.ui && m.ui.type === "ticket_summary") d.appendChild(summaryCard(m));
    if (m.ui && m.ui.type === "ticket_created") d.appendChild(el("span", "badge", "Mã yêu cầu: " + m.ui.code));
    if (m.ui && m.ui.type === "handoff_notice") d.appendChild(el("span", "badge", "Đã chuyển cho nhân viên"));
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  }

  function summaryCard(m) {
    var card = el("div", "card"), dl = el("dl");
    dl.appendChild(el("dt", null, "Loại")); dl.appendChild(el("dd", null, m.ui.ticket_type || ""));
    (m.ui.fields || []).forEach(function (f) { dl.appendChild(el("dt", null, f.label)); dl.appendChild(el("dd", null, f.value)); });
    var btns = el("div", "btns"), ok = el("button", null, "Xác nhận"), no = el("button", "alt", "Chỉnh sửa");
    ok.type = no.type = "button";
    ok.addEventListener("click", function () { lock(); send("", "confirm_ticket"); });
    no.addEventListener("click", function () { lock(); send("", "reject_ticket"); });
    function lock() { ok.disabled = no.disabled = true; }
    btns.appendChild(ok); btns.appendChild(no); card.appendChild(dl); card.appendChild(btns);
    return card;
  }

  function applyStatus(s) {
    status = s; statusEl.textContent = STATUS_TEXT[s] || s;
    var closed = s === "Closed";
    input.disabled = sendBtn.disabled = closed; restart.hidden = !closed;
    if (s === "Waiting_Agent" || s === "Agent_Handling") startPoll(); else stopPoll();
  }
  function startPoll() { if (!poll) poll = setInterval(fetchNew, 3000); }
  function stopPoll() { if (poll) { clearInterval(poll); poll = null; } }

  function apply(data) {
    if (data.session_token) { token = data.session_token; store("token", token); }
    if (data.session_id) { sid = data.session_id; store("sid", sid); }
    (data.messages || []).forEach(renderMessage);
    applyStatus(data.status);
  }

  function errorMessage(res, body) {
    var e = (body && body.error) || {};
    if (res.status === 429) return e.message || "Bạn gửi quá nhanh, vui lòng đợi một chút.";
    return e.message || "Có lỗi xảy ra, vui lòng thử lại.";
  }

  function send(text, action) {
    if (sending) return; sending = true; showBanner("");
    var cid = uuid();
    var pending = text ? bubble({ role: "customer", text: text, sources: [], ui: null }) : null;
    function dropPending() { if (pending && pending.parentNode) pending.parentNode.removeChild(pending); pending = null; }
    fetch("/api/chat/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": token || "" },
      body: JSON.stringify({ session_id: sid, text: text || null, client_msg_id: cid, action: action || null })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) { return { res: res, body: body }; });
    }).then(function (r) {
      if (r.res.ok) { dropPending(); apply(r.body); return; }
      dropPending();
      if (r.res.status === 403) { showBanner("Phiên không còn hợp lệ. Đang bắt đầu lại."); reset(true); return; }
      if (r.res.status === 409 && r.body.error && r.body.error.code === "session_closed") { applyStatus("Closed"); }
      showBanner(errorMessage(r.res, r.body));
    }).catch(function () { dropPending(); showBanner("Không kết nối được máy chủ. Vui lòng thử lại sau ít phút hoặc liên hệ hotline."); })
      .then(function () { sending = false; });
  }

  function fetchNew() {
    if (!sid) return;
    fetch("/api/chat/sessions/" + encodeURIComponent(sid) + "/messages?after=" + serverLastId(), { headers: { "X-Session-Token": token || "" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) apply(d); }).catch(function () {});
  }
  function serverLastId() { return lastId; }

  function reset(keepBanner) {
    stopPoll(); sid = token = null; lastId = 0; shown = {}; store("sid", null); store("token", null);
    log.textContent = ""; if (!keepBanner) showBanner(""); applyStatus("AI_Handling");
    greet();
  }
  function greet() {
    bubble({ role: "ai", text: "Xin chào, mình là trợ lý CSKH của Savani. Bạn cần hỗ trợ về đổi trả, bảo hành, đơn hàng hay vấn đề khác?", sources: [], ui: null });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault(); var t = input.value.trim(); if (!t) return;
    input.value = ""; send(t, null);
  });
  restart.addEventListener("click", function () { reset(false); });

  // Khôi phục phiên khi tải lại trang
  sid = load("sid"); token = load("token");
  if (sid && token) { applyStatus("AI_Handling"); fetch("/api/chat/sessions/" + encodeURIComponent(sid) + "/messages?after=0", { headers: { "X-Session-Token": token } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); }).then(apply).catch(function () { reset(false); }); }
  else greet();
})();
