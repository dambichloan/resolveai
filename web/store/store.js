(function () {
  "use strict";
  var P = [
    ["Áo sơ mi nam ngắn tay", 455000, 249000, "#cfd8e3", "#2f4a6b", "Mới", "https://cdn.hstatic.net/products/200000471735/mssa022s6__1__cbeaecd36dcf459fbb4e070a431c293e_icon.jpg"],
    ["Áo giữ nhiệt cổ tròn nam", 249000, 129000, "#e6ddd0", "#7a5c3a", "-49%", "https://cdn.hstatic.net/products/200000471735/mgnr103w6-1-k001__4__c06da4362a9e40bf93bea404a679419a_icon.jpg"],
    ["Áo giữ nhiệt cổ cao nữ", 299000, 129000, "#ecd0d4", "#8a1f2f", "-57%", "https://cdn.hstatic.net/products/200000471735/wgnc016w6-1-e001___1_7aa03c836120492ab098bf6286458f1c_icon.jpg"],
    ["Áo thun dài tay cổ bẻ nữ", 349000, 244300, "#e8e0ec", "#5a3f7a", "-30%", "https://cdn.hstatic.net/products/200000471735/wltb008w6-1-w001__4__720f0c7e87fd4ac1a8d77efc37af2451_icon.jpg"],
    ["Áo thun dài tay cổ tròn nam", 320000, 192000, "#d9d9db", "#3b3b40", "-40%", "https://cdn.hstatic.net/products/200000471735/mtfl004w6-2-w001__1__6b7a19ed2f494f6e808b843dab04b10a_icon.jpg"],
    ["Áo thun dài tay cổ tròn nữ", 299000, 209300, "#f0e3cf", "#a2692a", "-30%", "https://cdn.hstatic.net/products/200000471735/wtfl004w6-2-k001__1__b971ff4b20764cf2abaa8f12b3cd43fa_icon.jpg"],
    ["Áo giữ nhiệt cổ tròn nữ", 299000, 179400, "#d3e6e0", "#2a7a66", "-40%", "https://cdn.hstatic.net/products/200000471735/wgnr010w6-1-b011__4__2be046fd47c94657a88394804dab499f_icon.jpg"]
  ];
  var tee = '<svg viewBox="0 0 100 100" aria-hidden="true"><path d="M30 14l-22 14 8 16 12-6v44h44V38l12 6 8-16-22-14c-3 8-11 12-20 12s-17-4-20-12z" fill="C" stroke="D" stroke-width="2" stroke-linejoin="round"/></svg>';
  var money = function (n) { return n.toLocaleString("vi-VN") + "đ"; };
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; }
  var grid = document.getElementById("grid"), cartN = document.getElementById("cartN"), n = 0;
  P.forEach(function (p) {
    var card = el("article", "card"), img = el("div", "img");
    var photo = el("img", "product-photo");
    photo.src = p[6]; photo.alt = p[0]; photo.loading = "lazy";
    photo.addEventListener("error", function () {
      photo.remove(); img.style.background = p[3]; img.innerHTML = tee.replace("C", p[4]).replace("D", "#fff");
    });
    img.appendChild(photo);
    if (p[5]) img.appendChild(el("span", "tag", p[5]));
    card.appendChild(img); card.appendChild(el("h3", null, p[0]));
    var pr = el("div", "price"); pr.appendChild(el("b", null, money(p[2]))); pr.appendChild(el("s", null, money(p[1]))); card.appendChild(pr);
    var sz = el("div", "sizes");
    ["S", "M", "L", "XL"].forEach(function (s, i) {
      var b = el("button", null, s); b.type = "button"; b.setAttribute("aria-pressed", i === 1 ? "true" : "false");
      b.addEventListener("click", function () { Array.prototype.forEach.call(sz.children, function (x) { x.setAttribute("aria-pressed", "false"); }); b.setAttribute("aria-pressed", "true"); });
      sz.appendChild(b);
    });
    card.appendChild(sz);
    var add = el("button", "add", "Thêm vào giỏ"); add.type = "button";
    add.addEventListener("click", function () { cartN.textContent = ++n; });
    card.appendChild(add); grid.appendChild(card);
  });
})();
