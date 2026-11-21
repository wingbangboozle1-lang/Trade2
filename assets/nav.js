/* Progressive enhancement for the sidebar: the canonical navigation is
 * rendered server-side by site_build/build.py, so the menu is complete and in
 * the same order on every page with JavaScript disabled or before this file
 * runs. Everything here is additive and idempotent.
 *
 * What it does, and why each item is safe:
 *
 *   1. Scrolls the active link into view in a narrow viewport, so the trader
 *      always sees which topic they are on without hunting.
 *   2. Shows a "data age" dot on the sidebar footer that is derived from the
 *      snapshot timestamp already in the DOM (no network call, nothing
 *      invented). Green under 15 minutes, amber to 60, red beyond — the same
 *      thresholds the desk uses.
 *   3. Cross-links the secondary dashboard published under /kalshi-dashboard/,
 *      but only from a path prefix that is known to contain it.
 *
 * Nothing in this file changes the set of links that is present without it,
 * with the single documented exception of the cross-link in (3), which is what
 * it existed for.
 */
(function () {
  "use strict";

  /* Deployments that actually contain kalshi-dashboard/index.html. The root
   * site and the docs site are the two that do; category pages sit one level
   * deeper. Anything else (a local file, a preview server) gets no link. */
  var KNOWN_ROOTS = ["/Trade2/", "/Trade2/docs/"];

  var CROSSLINK = {
    label: "Session dashboard",
    title: "The separately built dashboard published next to this one. Same " +
           "public demo data; a different renderer. See the Overview page for " +
           "which one to use."
  };

  function crosslinkTarget() {
    var here = location.pathname.replace(/[^/]*$/, "");
    var known = KNOWN_ROOTS.some(function (root) {
      return here === root || here.indexOf(root) === 0;
    });
    if (!known) return null;
    /* Never link a page to its own deployment root: from /Trade2/docs/ the
     * file is directly under this prefix, from /Trade2/ it is one level down. */
    if (here === "/Trade2/") return here + "kalshi-dashboard/index.html";
    if (here === "/Trade2/docs/") return here + "kalshi-dashboard/index.html";
    return "/Trade2/kalshi-dashboard/index.html";
  }

  function addCrosslink() {
    var target = crosslinkTarget();
    if (!target || document.querySelector("[data-crosslink]")) return;
    var nav = document.querySelector('.side-nav[aria-label="Research"]')
           || document.querySelector(".side-nav");
    if (!nav) return;
    var a = document.createElement("a");
    a.href = target;
    a.setAttribute("data-crosslink", "1");
    a.innerHTML = "<span>▦</span> " + CROSSLINK.label;
    a.title = CROSSLINK.title;
    nav.appendChild(a);
  }

  function revealActive() {
    var active = document.querySelector(".side-nav a.active");
    if (!active || typeof active.scrollIntoView !== "function") return;
    var box = active.closest ? active.closest("aside") : null;
    if (box && box.scrollHeight <= box.clientHeight + 4) return;
    active.scrollIntoView({ block: "nearest" });
  }

  function stampAge() {
    var foot = document.querySelector(".sidebar-foot");
    if (!foot || foot.querySelector("[data-age]")) return;
    var node = document.getElementById("snapshotAge") ||
               document.querySelector("[data-generated-ts]");
    if (!node) return;
    var raw = node.getAttribute("data-generated-ts") || "";
    var ts = Number(raw);
    if (!raw || !isFinite(ts) || ts <= 0) return;
    var mins = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
    var dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("data-age", String(mins));
    dot.title = "Snapshot fetched " + mins + " min ago";
    if (mins >= 60) dot.style.background = "#d45d61";
    else if (mins >= 15) dot.style.background = "#d9a441";
    foot.insertBefore(dot, foot.firstChild);
  }

  function boot() {
    addCrosslink();
    revealActive();
    stampAge();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
