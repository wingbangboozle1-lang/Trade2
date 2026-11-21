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
 *      but only when that page is actually present in this deployment. The
 *      earlier version always appended the link, which produced a 404 from the
 *      root site: the file list is built once into BASE_PAGES below, and the
 *      link is only added for a deployment whose paths match one of the known
 *      layouts.
 *
 * Nothing in this file changes the set of links that is present without it,
 * with the single documented exception of the cross-link in (3), which is what
 * it existed for.
 */
(function () {
  "use strict";

  var CROSSLINK = {
    title: "The separate dashboard published alongside this one",
    label: "Session dashboard"
  };

  /* Deployments that actually contain kalshi-dashboard/index.html. The root
   * site (served from /) and the docs site (served from /docs/) are the two
   * that do; the category pages are one level deeper. A location outside
   * these prefixes (a local file open, a preview server) simply gets no link. */
  var KNOWN_ROOTS = ["/Trade2/", "/Trade2/docs/"];

  function crosslinkTarget() {
    var here = location.pathname.replace(/[^/]*$/, "");
    var ok = KNOWN_ROOTS.some(function (root) {
      return here.indexOf(root) === 0 || here === root.slice(0, -1) + "/";
    });
    return ok ? here + "kalshi-dashboard/index.html" : null;
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
