/* Installable app and the phone layout's small behaviours.
 *
 *  1. Registers the service worker (/sw.js) so the site can be installed.
 *  2. Offers "Install the app": the browser's own prompt where there is one
 *     (Android, desktop Chrome/Edge), the Share > Add to Home Screen steps on
 *     iPhone and iPad. Offered once per visit from the second visit on, never
 *     when already installed, and not again for two weeks after "Not now".
 *  3. Back buttons in the phone app bar ([data-m-back]).
 *  4. Refreshes the screen when you come back to the app after a minute away,
 *     or land on it again with the Back button (fires "m-refresh" on <body>).
 *  5. Puts the number of things waiting on the app icon where the platform
 *     supports it.
 *
 * Loaded before Alpine so mInstallSheet() exists when Alpine starts.
 */
(function () {
  'use strict';

  var SNOOZE_KEY = 'smm.install.snoozedUntil';
  var VISITS_KEY = 'smm.visits';
  var DAY = 864e5;
  var deferredPrompt = null;

  function stored(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function store(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }
  function session(key, value) {
    try {
      if (value === undefined) return window.sessionStorage.getItem(key);
      window.sessionStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }

  function isStandalone() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      window.navigator.standalone === true;
  }
  window.mIsStandalone = isStandalone;

  var ua = window.navigator.userAgent || '';
  var isIOS = /iPad|iPhone|iPod/.test(ua) ||
    (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);

  function isPhoneLayout() {
    return window.matchMedia && window.matchMedia('(max-width: 1023px)').matches;
  }

  /* 1. Service worker ------------------------------------------------- */
  if ('serviceWorker' in window.navigator && window.isSecureContext) {
    window.addEventListener('load', function () {
      window.navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () { /* not installable here */ });
    });
  }

  /* 2. Install ------------------------------------------------------- */
  // One visit = one browser session, however many pages it opens.
  if (!session('smm.session')) {
    session('smm.session', '1');
    store(VISITS_KEY, String((parseInt(stored(VISITS_KEY) || '0', 10) || 0) + 1));
  }

  function snoozed() {
    var until = parseInt(stored(SNOOZE_KEY) || '0', 10) || 0;
    return until > Date.now();
  }

  function maybeOffer() {
    if (isStandalone() || snoozed() || !isPhoneLayout()) return;
    if (!document.querySelector('.m-tabbar')) return;        // only inside the signed-in app
    if (session('smm.install.offered')) return;              // once per visit
    if ((parseInt(stored(VISITS_KEY) || '0', 10) || 0) < 2) return;
    if (!deferredPrompt && !isIOS) return;                   // nothing we could help with
    session('smm.install.offered', '1');
    window.setTimeout(function () {
      window.dispatchEvent(new CustomEvent('m-install-sheet'));
    }, 1500);
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();          // we show our own sheet instead of the mini-infobar
    deferredPrompt = event;
    window.dispatchEvent(new CustomEvent('m-install-available'));
    maybeOffer();
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    store(SNOOZE_KEY, String(Date.now() + 3650 * DAY));
  });

  document.addEventListener('DOMContentLoaded', maybeOffer);

  // Alpine component behind the install sheet (templates/mobile/partials/_sheets.html).
  window.mInstallSheet = function () {
    return {
      open: false,
      canPrompt: !!deferredPrompt,
      isIOS: isIOS,
      init: function () {
        var self = this;
        window.addEventListener('m-install-available', function () { self.canPrompt = true; });
      },
      show: function () {
        this.canPrompt = !!deferredPrompt;
        this.open = true;
      },
      close: function (snooze) {
        this.open = false;
        if (snooze) store(SNOOZE_KEY, String(Date.now() + 14 * DAY));
      },
      install: function () {
        var self = this;
        var prompt = deferredPrompt;
        if (!prompt) return;
        deferredPrompt = null;
        prompt.prompt();
        Promise.resolve(prompt.userChoice).catch(function () {}).then(function () {
          self.canPrompt = false;
          self.open = false;
        });
      },
    };
  };

  /* 3. Back buttons --------------------------------------------------- */
  document.addEventListener('click', function (event) {
    var button = event.target && event.target.closest ? event.target.closest('[data-m-back]') : null;
    if (!button) return;
    event.preventDefault();
    var fromHere = document.referrer && document.referrer.indexOf(window.location.origin + '/') === 0;
    if (fromHere && window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = button.getAttribute('data-m-fallback') || '/app/';
    }
  });

  /* 4. Fresh data when you come back ---------------------------------- */
  function refresh() {
    document.body.dispatchEvent(new CustomEvent('m-refresh', { bubbles: true }));
  }
  var hiddenAt = 0;
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      hiddenAt = Date.now();
      return;
    }
    if (hiddenAt && Date.now() - hiddenAt > 60000) refresh();
    hiddenAt = 0;
  });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) refresh();   // restored by Back from the browser's page cache
  });

  /* 5. App icon badge -------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.querySelector('.m-tabbar[data-badge]');
    if (!bar || !isStandalone() || !('setAppBadge' in window.navigator)) return;
    var count = parseInt(bar.getAttribute('data-badge') || '0', 10) || 0;
    var done = count > 0 ? window.navigator.setAppBadge(count) : window.navigator.clearAppBadge();
    if (done && done.catch) done.catch(function () { /* not allowed here */ });
  });
})();
