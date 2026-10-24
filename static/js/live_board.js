/* The live team view: quiet refreshes, the hour chart's tooltips, the check-in age.
 *
 * - A refresh whose board is unchanged (same data-board-digest) swaps nothing, so nothing
 *   moves under the reader; a response without a board (a login page, an error) is ignored,
 *   and the boards carry data-no-error-toast so a failed refresh never raises the error toast.
 * - Background refreshes never flash the page's loading bar.
 * - Open "Show as table" panels, focus and inner scroll positions survive a swap. Focus is
 *   found again by id, or else by the same kind of control with the same link and words, so a
 *   keyboard or screen-reader user is never thrown back to the top of the page.
 * - Only a change in the numbers is announced, politely (#team-live-announce).
 * - Hour chart: hover or focus a bar for "10:00–11:00 · 6 turns"; arrow keys move
 *   between hours and each hour is read out through a polite live region beside the chart
 *   ([data-chart-live]); Escape hides the tooltip. Text is set with textContent only.
 * - "checked 12 s ago" keeps counting between refreshes.
 */
(function () {
  "use strict";
  if (window.__smLiveBoard) return;
  window.__smLiveBoard = true;

  var SVG_NS = "http://www.w3.org/2000/svg";

  function isLive(elt) {
    return !!(elt && elt.hasAttribute && (elt.hasAttribute("data-live-board") || elt.hasAttribute("data-live-strip")));
  }

  function digestOf(html) {
    var match = /data-board-digest="([^"]*)"/.exec(html || "");
    return match ? match[1] : null;
  }

  function boardRoot(container) {
    if (!container) return null;
    if (container.hasAttribute("data-board-digest")) return container;
    return container.querySelector("[data-board-digest]");
  }

  /* ---- Quiet refresh ---------------------------------------------------- */

  // Capture on document so the page's loading bar (a listener on body) never sees a background refresh.
  ["htmx:beforeRequest", "htmx:afterRequest"].forEach(function (name) {
    document.addEventListener(
      name,
      function (event) {
        if (isLive(event.target)) event.stopPropagation();
      },
      true
    );
  });

  var saved = null;

  document.addEventListener("htmx:beforeSwap", function (event) {
    var elt = event.detail.elt;
    if (!isLive(elt)) return;
    var xhr = event.detail.xhr;
    var next = digestOf(event.detail.serverResponse);
    if (!xhr || xhr.status !== 200 || !next) {
      event.detail.shouldSwap = false;
      return;
    }
    var root = boardRoot(elt);
    if (root && root.getAttribute("data-board-digest") === next) {
      event.detail.shouldSwap = false;
      return;
    }
    saved = {
      announce: root ? root.getAttribute("data-announce") : null,
      open: Array.prototype.map.call(elt.querySelectorAll("details[open][id]"), function (d) {
        return d.id;
      }),
      focus: document.activeElement && elt.contains(document.activeElement) ? focusKey(document.activeElement, elt) : null,
      chartIndex: activeIndexOf(elt.querySelector("[data-hour-chart]")),
      scroll: Array.prototype.map.call(elt.querySelectorAll("[data-keep-scroll]"), function (box) {
        return [box.getAttribute("data-keep-scroll"), box.scrollTop];
      }),
    };
  });

  document.addEventListener("htmx:afterSettle", function (event) {
    var elt = event.detail.elt;
    var container = elt && elt.isConnected ? elt : document.getElementById("team-board") || document.getElementById("live-strip");
    if (!saved || !container) {
      init(document);
      return;
    }
    var state = saved;
    saved = null;
    state.open.forEach(function (id) {
      var details = document.getElementById(id);
      if (details) details.open = true;
    });
    state.scroll.forEach(function (pair) {
      var box = document.querySelector('[data-keep-scroll="' + pair[0] + '"]');
      if (box) box.scrollTop = pair[1];
    });
    init(document);
    if (state.focus) {
      var target = findFocus(state.focus, container);
      if (target) {
        target.focus({ preventScroll: true });
        if (target.hasAttribute("data-hour-chart") && state.chartIndex !== null) showBar(target, state.chartIndex);
      }
    }
    var root = boardRoot(document.getElementById("team-board"));
    var region = document.getElementById("team-live-announce");
    if (root && region) {
      var text = root.getAttribute("data-announce");
      if (text && text !== state.announce) region.textContent = text;
    }
  });

  /* ---- Focus that survives a swap ---------------------------------------- */

  var FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

  function focusablesIn(container) {
    return Array.prototype.slice.call(container.querySelectorAll(FOCUSABLE));
  }

  function signature(el) {
    var words = (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120);
    return [el.tagName, el.getAttribute("href") || "", el.getAttribute("name") || "", words].join("|");
  }

  // Remember the focused control by id, or else by what it is (kind, link, words) and where it sat.
  function focusKey(el, container) {
    var list = focusablesIn(container);
    var sig = signature(el);
    var same = list.filter(function (item) {
      return signature(item) === sig;
    });
    return { id: el.id || null, sig: sig, nth: same.indexOf(el), index: list.indexOf(el) };
  }

  // Find it again after the swap: same id, then the same control, then whatever now sits in its
  // place, then the board itself, so focus stays where the reader was instead of falling to <body>.
  function findFocus(key, container) {
    if (key.id) {
      var byId = document.getElementById(key.id);
      if (byId && container.contains(byId)) return byId;
    }
    var list = focusablesIn(container);
    var same = list.filter(function (item) {
      return signature(item) === key.sig;
    });
    if (same.length) return same[Math.max(0, Math.min(same.length - 1, key.nth))];
    if (list.length && key.index >= 0) return list[Math.min(list.length - 1, key.index)];
    if (!container.hasAttribute("tabindex")) container.setAttribute("tabindex", "-1");
    return container;
  }

  /* ---- Hour chart ------------------------------------------------------- */

  function hits(chart) {
    return chart ? chart.querySelectorAll("[data-hit]") : [];
  }

  function activeIndexOf(chart) {
    if (!chart || chart.__active === undefined || chart.__active === null) return null;
    return chart.__active;
  }

  function clearActive(chart) {
    chart.querySelectorAll('[data-active="true"]').forEach(function (rect) {
      rect.removeAttribute("data-active");
    });
  }

  function hideTip(chart) {
    var tip = chart.querySelector("[data-chart-tip]");
    if (tip) tip.classList.add("hidden");
    clearActive(chart);
    chart.__active = null;
  }

  function stoppedIcon() {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "12");
    svg.setAttribute("height", "12");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "#FEA69C"); /* danger-300: the stopped icon on the dark tooltip (8.77:1) */
    svg.setAttribute("stroke-width", "2.5");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    var octagon = document.createElementNS(SVG_NS, "path");
    octagon.setAttribute("d", "M7.9 2h8.2L22 7.9v8.2L16.1 22H7.9L2 16.1V7.9z");
    var cross = document.createElementNS(SVG_NS, "path");
    cross.setAttribute("d", "M15 9l-6 6M9 9l6 6");
    svg.appendChild(octagon);
    svg.appendChild(cross);
    return svg;
  }

  // Read the hour out for screen readers: the tooltip itself is visual only (aria-hidden, inside role=img).
  function announceBar(chart, hit) {
    var region = chart.parentNode ? chart.parentNode.querySelector("[data-chart-live]") : null;
    if (!region) return;
    var total = parseInt(hit.getAttribute("data-total"), 10) || 0;
    var failed = parseInt(hit.getAttribute("data-failed"), 10) || 0;
    var text = (hit.getAttribute("data-range") || "") + ": " + total + (total === 1 ? " turn" : " turns");
    if (failed) text += ", " + failed + " stopped";
    region.textContent = text;
  }

  function showBar(chart, index, announce) {
    var list = hits(chart);
    if (!list.length) return;
    index = Math.max(0, Math.min(list.length - 1, index));
    var hit = list[index];
    var tip = chart.querySelector("[data-chart-tip]");
    if (!tip) return;
    clearActive(chart);
    chart.querySelectorAll('[data-bar="' + index + '"]').forEach(function (rect) {
      rect.setAttribute("data-active", "true");
    });
    chart.__active = index;

    var total = parseInt(hit.getAttribute("data-total"), 10) || 0;
    var failed = parseInt(hit.getAttribute("data-failed"), 10) || 0;
    tip.textContent = "";
    var value = document.createElement("div");
    value.style.fontWeight = "600";
    value.textContent = total + (total === 1 ? " turn" : " turns");
    var range = document.createElement("div");
    range.style.color = "#CED2D7"; /* ink-300 on ink-900: 10.88:1 */
    range.textContent = hit.getAttribute("data-range") || "";
    tip.appendChild(value);
    tip.appendChild(range);
    if (failed) {
      var stopped = document.createElement("div");
      stopped.style.display = "flex";
      stopped.style.alignItems = "center";
      stopped.style.gap = "4px";
      stopped.style.marginTop = "2px";
      stopped.appendChild(stoppedIcon());
      var words = document.createElement("span");
      words.textContent = failed + " stopped";
      stopped.appendChild(words);
      tip.appendChild(stopped);
    }
    tip.classList.remove("hidden");

    var width = chart.clientWidth;
    var center = ((index + 0.5) / list.length) * width;
    var tipWidth = tip.offsetWidth;
    var left = Math.max(0, Math.min(width - tipWidth, center - tipWidth / 2));
    var svg = chart.querySelector("svg");
    var svgTop = svg ? svg.offsetTop : 0;
    var barTop = parseFloat(hit.getAttribute("data-top")) || 0;
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, svgTop + barTop - tip.offsetHeight - 8) + "px";
    if (announce) announceBar(chart, hit);
  }

  function initChart(chart) {
    if (chart.__liveReady) return;
    chart.__liveReady = true;
    chart.__active = null;
    chart.addEventListener("pointermove", function (event) {
      var hit = event.target.closest ? event.target.closest("[data-hit]") : null;
      if (hit) showBar(chart, parseInt(hit.getAttribute("data-hit"), 10));
    });
    chart.addEventListener("pointerleave", function () {
      if (document.activeElement !== chart) hideTip(chart);
    });
    chart.addEventListener("focus", function () {
      if (chart.__active === null || chart.__active === undefined) showBar(chart, hits(chart).length - 1);
    });
    chart.addEventListener("blur", function () {
      hideTip(chart);
    });
    chart.addEventListener("keydown", function (event) {
      var count = hits(chart).length;
      var current = chart.__active === null || chart.__active === undefined ? count - 1 : chart.__active;
      var next = null;
      if (event.key === "ArrowLeft") next = current - 1;
      else if (event.key === "ArrowRight") next = current + 1;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = count - 1;
      else if (event.key === "Escape") {
        hideTip(chart);
        return;
      }
      if (next !== null) {
        event.preventDefault();
        showBar(chart, next, true);
      }
    });
  }

  /* ---- Check-in age ----------------------------------------------------- */

  function shortAge(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) return seconds + " s";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min";
    if (seconds < 86400) return Math.floor(seconds / 3600) + " h";
    return Math.floor(seconds / 86400) + " d";
  }

  function elapsedText(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) return "under a minute";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + " min";
    var hours = Math.floor(minutes / 60);
    minutes = minutes % 60;
    if (hours < 24) return minutes ? hours + " h " + minutes + " min" : hours + " h";
    return Math.floor(hours / 24) + " d";
  }

  // The server's clock now, from the data-server-now of the nearest rendered block and how long ago it arrived.
  function serverNow(el) {
    var holder = el.closest("[data-server-now]");
    if (!holder) return null;
    var stamp = holder.getAttribute("data-server-now");
    if (holder.__stamp !== stamp) {
      holder.__stamp = stamp;
      holder.__renderedAt = Date.now();
    }
    var base = parseFloat(stamp);
    return isFinite(base) ? base + (Date.now() - holder.__renderedAt) / 1000 : null;
  }

  // Relative times keep counting between refreshes; a refresh that changes nothing else never swaps for them.
  function tickAges() {
    document.querySelectorAll("[data-live-age]").forEach(function (el) {
      var now = serverNow(el);
      var checkin = parseFloat(el.getAttribute("data-checkin"));
      if (now === null || !isFinite(checkin)) return;
      el.textContent = (el.getAttribute("data-prefix") || "checked") + " " + shortAge(now - checkin) + " ago";
    });
    document.querySelectorAll("[data-live-ago]").forEach(function (el) {
      var now = serverNow(el);
      var at = parseFloat(el.getAttribute("data-live-ago"));
      if (now !== null && isFinite(at)) el.textContent = shortAge(now - at);
    });
    document.querySelectorAll("[data-live-elapsed]").forEach(function (el) {
      var now = serverNow(el);
      var at = parseFloat(el.getAttribute("data-live-elapsed"));
      if (now !== null && isFinite(at)) el.textContent = elapsedText(now - at);
    });
  }

  function init(scope) {
    (scope || document).querySelectorAll("[data-hour-chart]").forEach(initChart);
    tickAges();
  }

  function start() {
    init(document);
    window.setInterval(function () {
      if (document.visibilityState === "visible") tickAges();
    }, 5000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
