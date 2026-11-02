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
 * not `n`), while a dialog is open, below 1024 px, on auto-repeat, while a key is being composed, when
 * another handler already took the key, and when single keys are off on this device
 * (localStorage.shortcuts = 'off', the list's switch: WCAG 2.1.4). The key is never typed.
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
  /** Inputs that take no typing; any other input is a text field. */
  var NOT_TYPED = ['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit'];
  var TYPED_ROLES = '[role="textbox"], [role="searchbox"], [role="combobox"], [role="spinbutton"]';

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

  function shows(element) {
    return !!(element && element.getClientRects && element.getClientRects().length);
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
    /** Leave for `url` (a test replaces it: jsdom does not navigate). */
    navigate: function (url) { window.location.assign(url); },
  };
  window.bbShortcuts = api;

  /**
   * The list of keys (base.html, data-testid "shortcuts-dialog"): opened by `?` and Ctrl/Cmd-/
   * (open-shortcuts), closed by Escape, the close button and the scrim, giving the focus back to what
   * had it. Its switch reads the setting each time it opens, so a choice made in another tab shows.
   */
  window.shortcutsList = function shortcutsList() {
    return {
      open: false,
      enabled: true,
      opener: null,
      show: function () {
        if (this.open) return;
        var active = document.activeElement;
        this.opener = active && active !== document.body ? active : null;
        this.enabled = isOn();
        this.open = true;
      },
      close: function () {
        if (!this.open) return;
        this.open = false;
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
