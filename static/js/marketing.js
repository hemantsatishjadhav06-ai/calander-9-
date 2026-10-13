/* Public marketing pages: progressive enhancement only.
   Everything here degrades to a fully readable page without JavaScript. */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Mobile navigation ------------------------------------------------------ */
  var nav = document.querySelector("[data-nav]");
  var toggle = document.querySelector("[data-nav-toggle]");
  if (nav && toggle) {
    function closeNav() {
      nav.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
      root.classList.remove("nav-open");
    }
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      root.classList.toggle("nav-open", open);
    });
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        closeNav();
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        closeNav();
        toggle.focus();
      }
    });
    window.addEventListener("resize", function () {
      if (window.getComputedStyle(toggle).display === "none") { closeNav(); }
    });
  }

  /* Sticky nav shadow once the page scrolls ------------------------------ */
  var header = document.querySelector("[data-header]");
  if (header) {
    var onScroll = function () {
      header.classList.toggle("is-scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* Reveal-on-scroll ------------------------------------------------------ */
  var revealables = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealables.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.1 });
    revealables.forEach(function (el) { observer.observe(el); });
  }

  /* Copy buttons on code blocks ------------------------------------------ */
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.getElementById(button.getAttribute("data-copy"));
      if (!target || !navigator.clipboard) { return; }
      var label = button.textContent;
      navigator.clipboard.writeText(target.textContent.trim()).then(function () {
        button.textContent = "Copied";
        button.classList.add("is-done");
        setTimeout(function () {
          button.textContent = label;
          button.classList.remove("is-done");
        }, 1600);
      }).catch(function () {
        button.textContent = "Select and copy the code";
        setTimeout(function () { button.textContent = label; }, 2400);
      });
    });
  });

  /* Current year in the footer ------------------------------------------- */
  var year = document.querySelector("[data-year]");
  if (year) { year.textContent = String(new Date().getFullYear()); }
})();
