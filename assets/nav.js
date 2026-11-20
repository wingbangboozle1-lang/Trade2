/* Cross-link the independent dashboard that other sessions publish under
 * /kalshi-dashboard/, so a visitor on any page can reach every view.
 *
 * Deliberately a separate file rather than an edit to assets/app.js: that file
 * is owned by another session, and appending to it in place would create merge
 * conflicts on every one of their future pushes.
 */
(function () {
  "use strict";
  var here = location.pathname.replace(/[^/]*$/, "");
  var target = here + "kalshi-dashboard/index.html";
  function add() {
    var nav = document.querySelector('.side-nav[aria-label="Research"]')
           || document.querySelector(".side-nav");
    if (!nav || document.querySelector("[data-crosslink]")) return;
    var a = document.createElement("a");
    a.href = target;
    a.setAttribute("data-crosslink", "1");
    a.innerHTML = "<span>▦</span> Session dashboard";
    a.title = "The separate dashboard published by another session on this repo";
    nav.appendChild(a);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", add);
  } else {
    add();
  }
})();
