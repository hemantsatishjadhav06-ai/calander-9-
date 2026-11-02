/* Keyboard shortcuts (spec D16; Phase 3 T20). base.html loads this deferred, before Alpine, on every
 * workspace page (where Go to is), and holds the list of keys (shortcutsList(), data-testid
 * "shortcuts-dialog").
 *
 * From 1024 px:
 * - `n` opens the New post sheet where its trigger is (Home and Calendar: new-post:open, which
 *   static/js/new-post-sheet.js answers, remembering what had the focus), and elsewhere goes to Home's
 *   #new-post, for someone who may start posts only: the list's root names that address in
 *   data-new-post-url (sidebar_context's new_post_url), and leaves it out for anyone else.
 * - `/` opens Go to (open-palette, base.html's commandPalette()).
 * - `?` opens the list (open-shortcuts).
 * Each is ignored while a text field, a select or an editable region has the focus, with Ctrl, Alt or
 * Meta (Shift only where it makes the character: `?`, and `/` on keyboards that need it; Shift-N is
 * not `n`), while a dialog is open (one that shows: a closed drawer kept in the page does not count,
 * shows()), below 1024 px, on auto-repeat, while a key is being composed, when another handler
 * already took the key, and when single keys are off on this device (localStorage.shortcuts = 'off',
 * the list's switch: WCAG 2.1.4). The key is never typed.
 * - Ctrl-/ or Cmd-/ opens the list too, with single keys on or off and from a field (a modifier
 *   shortcut, like Ctrl-K for Go to), so the switch can always be turned back on.
 *
 * Storage may be blocked (a private window, cleared or blocked site data): reading it then counts as
 * on, and the switch still turns the keys off for this page. tests/js/shortcuts.test.cjs runs this file
 * as it is; tests/e2e/self/shortcuts.spec.ts in the browser.
 */
(function () {
  'use strict';

  var KEY = 'shortcuts';
  var OFF = 'off';
  var DESKTOP = '(min-width: 1024px)';
  var TRIGGER = '[aria-controls="new-post-sheet"]';
  var ROOT = '[data-shortcuts]';
  var NEW_POST = '#new-post';
  var DIALOGS = '[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog[open]';
  /** Hidden from everyone, whatever its box: a closed drawer says so, and so does what a trap shuts. */
  var UNSEEN = '[aria-hidden="true"], [inert]';
  /** Inputs that take no typing; any other input is a text field. */
  var NOT_TYPED = ['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit'];
  var TYPED_ROLES = '[role="textbox"], [role="searchbox"], [role="combobox"], [role="spinbutton"]';
  /**
   * The focus plugin's wait before it starts a trap: x-trap calls setTimeout(activate, 15) when its
   * expression turns true (static/js/vendor/alpine-focus.min.js; tests/js/shortcuts.test.cjs reads it
   * there, so an upgrade that changes it fails a test).
   */
  var PLUGIN_TRAP_DELAY_MS = 15;

  /** The switch's value when storage cannot keep it: this page only. */
  var memory = null;

  function storage() {
    return window.localStorage;
  }

  /** Whether single-key shortcuts are on: the device's setting, else this page's, else on. */
  function isOn() {
    try {
      var value = storage().getItem(KEY);
      if (value !== null) return value !== OFF;
    } catch (error) { /* blocked storage: this page's choice, else on */ }
    return memory !== OFF;
  }

  /** Turn single-key shortcuts on or off, on this device when it can keep it. */
  function setOn(on) {
    memory = on ? 'on' : OFF;
    try {
      if (on) storage().removeItem(KEY);
      else storage().setItem(KEY, OFF);
    } catch (error) { /* kept for this page only */ }
  }

  function wide() {
    if (typeof window.matchMedia === 'function') return window.matchMedia(DESKTOP).matches;
    return window.innerWidth >= 1024;
  }

  /**
   * Whether `element` really shows. Having a box is not enough: a drawer that stays in the page while
   * closed (Analytics' Post details) keeps its box slid out of view and is hidden by visibility: hidden
   * and aria-hidden="true" instead. Computed visibility is inherited, so a hidden ancestor counts.
   */
  function shows(element) {
    if (!element || !element.getClientRects || !element.getClientRects().length) return false;
    if (element.closest(UNSEEN)) return false;
    var style = window.getComputedStyle(element);
    return style.visibility !== 'hidden' && style.visibility !== 'collapse';
  }

  /** Whether `element` takes typing: a text field, a text area, a select or an editable region. */
  function typing(element) {
    if (!element || element.nodeType !== 1) return false;
    var tag = element.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (tag === 'INPUT') return NOT_TYPED.indexOf((element.getAttribute('type') || 'text').toLowerCase()) < 0;
    if (element.isContentEditable) return true;
    if (element.closest('[contenteditable]:not([contenteditable="false"])')) return true;
    return !!element.closest(TYPED_ROLES);
  }

  /** Whether a dialog shows: the sheet, Go to, the list, the notifications drawer, a page's own. */
  function dialogOpen() {
    return Array.prototype.some.call(document.querySelectorAll(DIALOGS), shows);
  }

  /**
   * What `event` (a keydown) asks for: 'new-post', 'go-to', 'list', or null for nothing.
   * Every guard is here; run() does what it names.
   */
  function match(event) {
    if (!event || event.defaultPrevented || event.repeat || event.isComposing || event.altKey) return null;
    var key = event.key;
    var command = event.ctrlKey || event.metaKey;
    var name = null;
    if (command) name = key === '/' ? 'list' : null;
    else if ((key === 'n' || key === 'N') && !event.shiftKey) name = 'new-post'; // N: Caps Lock
    else if (key === '/') name = 'go-to';
    else if (key === '?') name = 'list';
    if (!name) return null;
    if (!command && (!isOn() || typing(event.target) || typing(document.activeElement))) return null;
    if (!wide() || dialogOpen()) return null;
    return name;
  }

  /** The address `n` goes to away from the sheet: Home's #new-post, or '' when the person may not. */
  function newPostUrl() {
    var root = document.querySelector(ROOT);
    var url = root ? root.getAttribute('data-new-post-url') || '' : '';
    return url.indexOf(NEW_POST) > 0 ? url : '';
  }

  /** Do what `name` asks; false when there is nothing to do here (the key then stays the page's). */
  function run(name) {
    if (name === 'new-post') {
      if (document.querySelector(TRIGGER)) {
        window.dispatchEvent(new CustomEvent('new-post:open', { detail: {} }));
        return true;
      }
      var url = newPostUrl();
      if (!url) return false;
      api.navigate(url);
      return true;
    }
    if (name === 'go-to') {
      window.dispatchEvent(new CustomEvent('open-palette'));
      return true;
    }
    if (name === 'list') {
      window.dispatchEvent(new CustomEvent('open-shortcuts'));
      return true;
    }
    return false;
  }

  function onKeydown(event) {
    var name = match(event);
    if (name && run(name)) event.preventDefault();
  }

  var api = {
    isOn: isOn,
    setOn: setOn,
    match: match,
    run: run,
    /** The focus plugin's trap delay this file waits for (tests/js/shortcuts.test.cjs checks it). */
    pluginTrapDelayMs: PLUGIN_TRAP_DELAY_MS,
    /** Leave for `url` (a test replaces it: jsdom does not navigate). */
    navigate: function (url) { window.location.assign(url); },
  };
  window.bbShortcuts = api;

  /**
   * The list of keys (base.html, data-testid "shortcuts-dialog"): opened by `?` and Ctrl/Cmd-/
   * (open-shortcuts), closed by Escape, the close button and the scrim, giving the focus back to what
   * had it. Its switch reads the setting each time it opens, so a choice made in another tab shows.
   *
   * The list places the focus itself, like Go to and the New post sheet: on its close button the moment
   * it opens, and back to the opener when it closes. Its x-trap (noautofocus, noreturn) only keeps Tab
   * inside, and it starts late, so a key pressed before then would land outside the list (CI pressed
   * Escape there and the list stayed open); Escape also closes it from anywhere (base.html's window
   * listener).
   *
   * `trapped` holds the trap. A trap let go before the plugin started it would start anyway, on the
   * closed list, and keep Tab from moving anywhere on the page (WCAG 2.1.2). So the list lets it go only
   * once it has started: `trapStarted` turns true in a timer of the plugin's own length scheduled after
   * the plugin's (from $nextTick, which Alpine runs after the effect that schedules it), and timers of
   * equal length run in the order they were scheduled, however late a busy page runs them. A wall-clock
   * margin is not enough: a busy page ran the plugin's 15 ms timer after 30 ms.
   */
  window.shortcutsList = function shortcutsList() {
    return {
      open: false,
      trapped: false,
      trapStarted: false,
      enabled: true,
      opener: null,
      _marking: false,
      show: function () {
        if (this.open) return;
        var active = document.activeElement;
        this.opener = active && active !== document.body ? active : null;
        this.enabled = isOn();
        if (!this.trapped) this.trapStarted = false;
        this.trapped = true;
        this.open = true;
        var list = this;
        this.$nextTick(function () {
          list.markTrapStarted();
          list.placeFocus(10);
        });
      },
      /** Once the plugin has started the trap: note it, and let it go if the list closed meanwhile. */
      markTrapStarted: function () {
        if (this._marking || this.trapStarted) return;
        this._marking = true;
        var list = this;
        setTimeout(function () {
          list._marking = false;
          list.trapStarted = true;
          if (!list.open) list.trapped = false;
        }, PLUGIN_TRAP_DELAY_MS);
      },
      /** Put the focus on the close button, trying again on the next frames until it lands. */
      placeFocus: function (tries) {
        var refs = this.$refs || {};
        if (!this.open || !refs.dialog || !refs.close || refs.dialog.contains(document.activeElement)) return;
        refs.close.focus();
        var list = this;
        if (tries > 0 && document.activeElement !== refs.close && typeof window.requestAnimationFrame === 'function') {
          window.requestAnimationFrame(function () { list.placeFocus(tries - 1); });
        }
      },
      close: function () {
        if (!this.open) return;
        this.open = false;
        if (this.trapStarted) this.trapped = false; // else markTrapStarted lets it go
        var opener = this.opener;
        this.opener = null;
        if (opener && opener.isConnected && typeof opener.focus === 'function') {
          this.$nextTick(function () { opener.focus(); });
        }
      },
      setEnabled: function (on) {
        setOn(!!on);
        this.enabled = isOn();
      },
    };
  };

  document.addEventListener('keydown', onKeydown);
})();
