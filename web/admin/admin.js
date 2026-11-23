// Nội dung động chỉ gắn bằng textContent (chống XSS). Không dùng innerHTML.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var cur = { queue: null, ticket: null, history: null, kb: null }, tab = "queue", timer = null;
  var ROLE = { customer: "Khách", ai: "AI", staff: "Nhân viên", system: "" };
  var NEXT = { "Mới": "Đang xử lý", "Đang xử lý": "Đã hoàn thành" };
  var STATUS = { AI_Handling: ["AI đang xử lý", "green"], Waiting_Agent: ["Chờ nhân viên", "red"], Agent_Handling: ["Nhân viên đang xử lý", "dark"], Closed: ["Đã đóng", ""] };
  var TSTATUS = { "Mới": "red", "Đang xử lý": "amber", "Đã hoàn thành": "green" };
  var HO = { "HO-01": "Không đủ căn cứ trả lời", "HO-03": "Khách yêu cầu gặp nhân viên", "HO-04": "Khách bức xúc / khiếu nại", "HO-07": "Vượt phạm vi xử lý an toàn (xác thực đơn sai nhiều lần)", "HO-08": "Lỗi hệ thống Agent" };
  var HERO = {
    queue: ["Hàng đợi hỗ trợ", "Tiếp nhận các cuộc trò chuyện mà trợ lý AI đã chuyển cho nhân viên."],
    tickets: ["Ticket", "Yêu cầu đổi trả, bảo hành và khiếu nại đã được ghi nhận. Mã Ticket theo dạng TK-YYYYMMDDXXXX."],
    history: ["Lịch sử hội thoại", "Xem lại mọi phiên chat, kể cả phiên AI tự giải quyết."],
    dash: ["Thống kê", "Hiệu quả của trợ lý AI và tình hình xử lý Ticket."],
    kb: ["Tài liệu KB", "Chính sách đổi trả, bảo hành, bảng size và giờ làm việc mà trợ lý AI dùng để trả lời."]
  };
  function statusLabel(s) { return (STATUS[s] || [s, ""])[0]; }
  function pill(text, cls) { return el("span", "pill" + (cls ? " " + cls : ""), text); }
  function statusPill(s) { return pill(statusLabel(s), (STATUS[s] || ["", ""])[1]); }
  function hoText(c) { return c ? (HO[c] ? c + " · " + HO[c] : c) : ""; }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? (iso || "") : d.toLocaleString("vi-VN", { hour12: false }); }

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function toast(t) { var b = $("toast"); b.textContent = t; b.hidden = false; setTimeout(function () { b.hidden = true; }, 4000); }

  function api(method, url, body) {
    return fetch(url, { method: method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, credentials: "same-origin" })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) { var e = new Error((j.error && j.error.message) || "Lỗi"); e.status = r.status; e.code = j.error && j.error.code; throw e; }
          return j;
        });
      });
  }
  function fail(e) { toast(e.message); }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  $("tabs").addEventListener("click", function (e) { if (e.target.dataset.tab) setTab(e.target.dataset.tab); });

  function setTab(t) {
    tab = t;
    ["queue", "tickets", "history", "dash", "kb"].forEach(function (n) { $("tab-" + n).hidden = n !== t; });
    $("heroTitle").textContent = HERO[t][0]; $("heroSub").textContent = HERO[t][1];
    Array.prototype.forEach.call($("tabs").children, function (b) { b.classList.toggle("on", b.dataset.tab === t); });
    refresh(); stop(); timer = setInterval(refresh, 5000);
  }
  function refresh() {
    if (tab === "queue") { loadQueue(); if (cur.queue) loadConv(cur.queue, $("conv"), true); }
    else if (tab === "tickets") loadTickets();
    else if (tab === "history") loadHistory();
    else if (tab === "dash") loadDash();
    else if (tab === "kb") loadKb();
    if (tab !== "queue") countQueue();
  }
  function countQueue() {
    api("GET", "/api/admin/queue").then(function (d) { showCount(d.items.length); }).catch(function () {});
  }
  function showCount(n) { var b = $("queueN"); b.textContent = String(n); b.hidden = !n; }

  // ---- Hàng đợi + hội thoại
  function loadQueue() {
    api("GET", "/api/admin/queue").then(function (d) {
      var box = $("queueList"); clear(box); showCount(d.items.length);
      if (!d.items.length) box.appendChild(el("p", "muted", "Hàng đợi trống."));
      d.items.forEach(function (it) {
        var n = el("div", "item" + (it.session_id === cur.queue ? " sel" : ""));
        var top = el("div", "top"); top.appendChild(el("strong", null, it.intent || "Chưa phân loại")); top.appendChild(pill(hoText(it.handoff_reason), "red")); n.appendChild(top);
        n.appendChild(el("div", null, it.last_customer_message || ""));
        n.appendChild(el("small", null, when(it.handoff_at) + (it.tickets && it.tickets.length ? " · " + it.tickets.join(", ") : "")));
        n.addEventListener("click", function () { cur.queue = it.session_id; loadQueue(); loadConv(it.session_id, $("conv"), true); });
        box.appendChild(n);
      });
    }).catch(fail);
  }
  function renderMsgs(list) {
    var box = el("div", "msgs");
    list.forEach(function (m) {
      var d = el("div", "m " + m.role);
      if (ROLE[m.role]) d.appendChild(el("b", null, ROLE[m.role]));
      d.appendChild(document.createTextNode(m.text));
      box.appendChild(d);
    });
    return box;
  }
  function loadConv(id, target, actions) {
    api("GET", "/api/admin/sessions/" + encodeURIComponent(id)).then(function (d) {
      var prev = target.querySelector("input.reply"), draft = prev ? prev.value : "", focus = prev && document.activeElement === prev;
      clear(target);
      var head = el("div", "row");
      head.appendChild(statusPill(d.status)); head.appendChild(el("strong", null, d.intent || "Chưa phân loại")); if (d.handoff_reason) head.appendChild(pill(hoText(d.handoff_reason), "red"));
      target.appendChild(head);
      if (d.tickets.length) target.appendChild(el("div", "muted", "Ticket liên quan: " + d.tickets.map(function (t) { return t.id + " (" + t.status + ")"; }).join(", ")));
      if (d.sources.length) target.appendChild(el("div", "muted", "Nguồn đã dùng: " + d.sources.map(function (s) { return s.title; }).join("; ")));
      var msgs = renderMsgs(d.messages); target.appendChild(msgs); msgs.scrollTop = msgs.scrollHeight;
      if (!actions) return;
      var row = el("div", "row");
      if (d.status === "Waiting_Agent") {
        var b = el("button", "primary", "Tiếp nhận"); b.addEventListener("click", function () { b.disabled = true; api("POST", "/api/admin/sessions/" + id + "/claim").then(function () { loadQueue(); loadConv(id, target, true); }).catch(function (e) { fail(e); loadQueue(); loadConv(id, target, true); }); });
        row.appendChild(b);
      } else if (d.status === "Agent_Handling") {
        var inp = el("input", "reply"); inp.placeholder = "Nhập phản hồi..."; inp.maxLength = 1000; inp.value = draft;
        var send = el("button", "primary", "Gửi"), end = el("button", null, "Kết thúc");
        function go() { var t = inp.value.trim(); if (!t) return; send.disabled = true; api("POST", "/api/admin/sessions/" + id + "/messages", { text: t }).then(function () { loadConv(id, target, true); }).catch(function (e) { fail(e); send.disabled = false; }); }
        send.addEventListener("click", go); inp.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
        end.addEventListener("click", function () { api("POST", "/api/admin/sessions/" + id + "/close").then(function () { cur.queue = null; clear(target); target.appendChild(el("p", "muted", "Đã kết thúc phiên.")); loadQueue(); }).catch(fail); });
        row.appendChild(inp); row.appendChild(send); row.appendChild(end);
        if (focus) setTimeout(function () { inp.focus(); }, 0);
      }
      target.appendChild(row);
    }).catch(fail);
  }

  // ---- Ticket
  function loadTickets() {
    var q = []; if ($("fStatus").value) q.push("status=" + encodeURIComponent($("fStatus").value)); if ($("fType").value) q.push("type=" + encodeURIComponent($("fType").value));
    api("GET", "/api/admin/tickets?" + q.join("&")).then(function (d) {
      var box = $("ticketList"); clear(box);
      if (!d.items.length) box.appendChild(el("p", "muted", "Không có Ticket."));
      d.items.forEach(function (t) {
        var n = el("div", "item" + (t.id === cur.ticket ? " sel" : ""));
        var tp = el("div", "top"); tp.appendChild(el("strong", null, t.id)); tp.appendChild(pill(t.status, TSTATUS[t.status])); n.appendChild(tp);
        n.appendChild(el("div", null, t.type + " · " + (t.customer_name || ""))); n.appendChild(el("small", null, when(t.created_at)));
        n.addEventListener("click", function () { cur.ticket = t.id; showTicket(t.id); loadTickets(); });
        box.appendChild(n);
      });
    }).catch(fail);
  }
  $("fStatus").addEventListener("change", loadTickets); $("fType").addEventListener("change", loadTickets);
  function showTicket(id) {
    api("GET", "/api/admin/tickets/" + encodeURIComponent(id)).then(function (t) {
      var box = $("ticketDetail"); clear(box);
      box.appendChild(el("h3", null, t.id)); var hr = el("div", "row"); hr.appendChild(el("strong", null, t.type)); hr.appendChild(pill(t.status, TSTATUS[t.status])); box.appendChild(hr);
      var kv = el("dl", "kv");
      [["Khách", t.customer_name], ["Liên hệ", t.contact], ["Mã đơn", t.order_id], ["Sản phẩm", t.product], ["Mô tả", t.description], ["Tạo lúc", when(t.created_at)]].forEach(function (p) {
        if (p[1]) { kv.appendChild(el("dt", null, p[0])); kv.appendChild(el("dd", null, p[1])); }
      });
      box.appendChild(kv);
      box.appendChild(el("h4", null, "Lịch sử"));
      t.history.forEach(function (h) { box.appendChild(el("div", "muted", when(h.created_at) + " · " + (h.old_status || "—") + " → " + h.new_status + (h.note ? " · " + h.note : ""))); });
      var nx = NEXT[t.status];
      if (nx) {
        var row = el("div", "row"), note = el("input"); note.placeholder = nx === "Đã hoàn thành" ? "Ghi chú kết quả (bắt buộc)" : "Ghi chú (không bắt buộc)";
        var b = el("button", "primary", "Chuyển sang: " + nx);
        b.addEventListener("click", function () { api("PATCH", "/api/admin/tickets/" + encodeURIComponent(id) + "/status", { status: nx, note: note.value }).then(function () { showTicket(id); loadTickets(); }).catch(fail); });
        row.appendChild(note); row.appendChild(b); box.appendChild(row);
      }
    }).catch(fail);
  }

  // ---- Lịch sử
  function loadHistory() {
    var s = $("hStatus").value;
    api("GET", "/api/admin/sessions" + (s ? "?status=" + encodeURIComponent(s) : "")).then(function (d) {
      var box = $("historyList"); clear(box);
      if (!d.items.length) box.appendChild(el("p", "muted", "Chưa có phiên."));
      d.items.forEach(function (it) {
        var n = el("div", "item" + (it.session_id === cur.history ? " sel" : ""));
        var ht = el("div", "top"); ht.appendChild(el("strong", null, it.intent || "Chưa phân loại")); ht.appendChild(statusPill(it.status)); n.appendChild(ht); n.appendChild(el("small", null, when(it.updated_at)));
        n.addEventListener("click", function () { cur.history = it.session_id; loadConv(it.session_id, $("historyDetail"), false); loadHistory(); });
        box.appendChild(n);
      });
    }).catch(fail);
  }
  $("hStatus").addEventListener("change", loadHistory);

  // ---- Thống kê
  function loadDash() {
    api("GET", "/api/admin/dashboard").then(function (d) {
      var box = $("dash"); clear(box); box.className = "dash";
      var stats = el("ul", "stats");
      function stat(label, value) { var li = el("li"); li.appendChild(el("b", "n", String(value))); li.appendChild(el("span", null, label)); stats.appendChild(li); }
      stat("Tổng số phiên", d.total_sessions);
      stat("Tỷ lệ AI tự giải quyết", d.ai_self_resolved_rate == null ? "—" : Math.round(d.ai_self_resolved_rate * 100) + "%");
      stat("Độ trễ TB của AI (ms)", d.avg_latency_ms == null ? "—" : d.avg_latency_ms);
      box.appendChild(stats);
      function bars(title, obj, cls) {
        box.appendChild(el("h2", null, title));
        var wrap = el("div", "bars"), keys = Object.keys(obj), max = Math.max.apply(null, keys.map(function (k) { return obj[k]; }).concat([1]));
        keys.forEach(function (k) {
          var r = el("div", "bar " + cls); r.appendChild(el("span", null, k));
          var track = el("div"), fill = el("i"); fill.style.width = Math.round(obj[k] / max * 100) + "%"; track.appendChild(fill); r.appendChild(track);
          r.appendChild(el("b", null, String(obj[k]))); wrap.appendChild(r);
        });
        box.appendChild(wrap);
      }
      bars("Ticket theo trạng thái", d.tickets_by_status, "");
      bars("Phân bố ý định (intent)", d.intent_distribution, "dark");
    }).catch(fail);
  }

  // ---- Tài liệu KB (xem và thêm mới)
  function loadKb() {
    api("GET", "/api/admin/kb/docs").then(function (d) {
      var box = $("kbList"); clear(box);
      if (!d.items.length) box.appendChild(el("p", "muted", "Chưa có tài liệu trong data/policies."));
      d.items.forEach(function (it) {
        var n = el("div", "item" + (it.doc_code === cur.kb ? " sel" : ""));
        var top = el("div", "top"); top.appendChild(el("strong", null, it.doc_code)); top.appendChild(pill(it.is_active ? "Đang hiệu lực" : "Hết hiệu lực", it.is_active ? "green" : ""));
        n.appendChild(top); n.appendChild(el("div", null, it.title));
        n.appendChild(el("small", null, "Phiên bản " + it.version + " · hiệu lực từ " + it.effective_date));
        n.addEventListener("click", function () { cur.kb = it.doc_code; showKb(it.doc_code); loadKb(); });
        box.appendChild(n);
      });
    }).catch(fail);
  }
  function renderMd(text) {
    var box = el("div", "doc"), ul = null;
    text.split("\n").forEach(function (line) {
      var m;
      if (/^\s*$/.test(line)) { ul = null; return; }
      if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) { ul = null; box.appendChild(el(m[1].length === 1 ? "h1" : "h2", null, m[2])); }
      else if ((m = /^\s*[-*]\s+(.*)$/.exec(line))) { if (!ul) { ul = el("ul"); box.appendChild(ul); } ul.appendChild(el("li", null, m[1])); }
      else if ((m = /^>\s?(.*)$/.exec(line))) { ul = null; box.appendChild(el("blockquote", null, m[1])); }
      else { ul = null; box.appendChild(el("p", null, line)); }
    });
    return box;
  }
  function showKb(code) {
    api("GET", "/api/admin/kb/docs/" + encodeURIComponent(code)).then(function (d) {
      var box = $("kbDoc"); clear(box);
      var row = el("div", "row"); row.appendChild(pill(d.doc_code, "red")); row.appendChild(pill(d.doc_type)); row.appendChild(el("span", "muted", "v" + d.version + " · hiệu lực từ " + d.effective_date + " · " + d.source_file));
      box.appendChild(row); box.appendChild(renderMd(d.content));
      box.appendChild(el("p", "muted", "Sửa và xóa tài liệu chưa hiện thực; hiện chỉ thêm mới."));
    }).catch(fail);
  }

  function kbField(box, label, node) {
    var w = el("label", null); w.style.display = "flex"; w.style.flexDirection = "column"; w.style.gap = "4px";
    w.appendChild(el("span", null, label)); w.appendChild(node); box.appendChild(w); return node;
  }
  function showKbForm() {
    cur.kb = null; loadKb();
    var box = $("kbDoc"); clear(box); box.appendChild(el("h1", null, "Thêm tài liệu"));
    box.appendChild(el("p", "muted", "Tài liệu được lưu vào kho chính sách và trợ lý AI dùng ngay cho các câu hỏi sau, không cần khởi động lại. Trong nội dung có thể dùng tiêu đề (## Mục) và gạch đầu dòng (- ý) để chia đoạn."));
    var form = el("div"); form.style.display = "flex"; form.style.flexDirection = "column"; form.style.gap = "12px"; box.appendChild(form);
    var title = kbField(form, "Tiêu đề", el("input")); title.maxLength = 200; title.placeholder = "Ví dụ: Chính sách thành viên";
    var type = kbField(form, "Loại tài liệu", el("select"));
    [["policy", "Chính sách"], ["faq", "Câu hỏi thường gặp"]].forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; type.appendChild(op); });
    var date = kbField(form, "Ngày hiệu lực (để trống = hôm nay)", el("input")); date.type = "date";
    var content = kbField(form, "Nội dung", el("textarea")); content.rows = 14; content.maxLength = 20000; content.placeholder = "Dán hoặc gõ nội dung tài liệu…";
    var actions = el("div", "row"), save = el("button", "primary", "Lưu tài liệu"), cancel = el("button", null, "Hủy");
    actions.appendChild(save); actions.appendChild(cancel); form.appendChild(actions);
    cancel.addEventListener("click", function () { clear(box); box.appendChild(el("p", "muted", "Chọn một tài liệu để xem nội dung.")); });
    save.addEventListener("click", function () {
      if (!title.value.trim() || !content.value.trim()) { toast("Cần nhập cả tiêu đề và nội dung."); return; }
      save.disabled = true;
      api("POST", "/api/admin/kb/docs", { title: title.value, content: content.value, doc_type: type.value, effective_date: date.value || null })
        .then(function (d) { toast("Đã thêm tài liệu " + d.doc_code); cur.kb = d.doc_code; loadKb(); showKb(d.doc_code); })
        .catch(function (e) { save.disabled = false; fail(e); });
    });
    title.focus();
  }
  $("kbAdd").addEventListener("click", showKbForm);

  setTab("queue");
})();
