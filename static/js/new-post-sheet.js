/* The New post sheet (templates/components/new_post_sheet.html; Phase 3, screen 1).
 *
 * newPostSheet() is the sheet's Alpine component. It is loaded deferred before Alpine on Home and
 * Calendar only, so it is defined when Alpine starts. The sheet sits inside the shell's Alpine scope,
 * so `this.mobileMenuOpen` is the shell's: opening closes the phone drawer first (its focus trap would
 * otherwise pull focus back), then the sheet traps focus itself (x-trap, no autofocus, no return).
 *
 * - Opens on the `new-post:open` window event (components/primary_action.html sends it; a Calendar cell
 *   adds `{mode: 'self', date, time, account}`) and on `#new-post`, on load or later.
 * - Remembers the opener (the element that sent the event, else the focused one, else the New post
 *   button) and gives focus back to it when the sheet closes (Escape, the close button, the scrim); when
 *   the opener cannot take it (a cell's hover-only "+", hidden again), the New post button does.
 * - Puts focus in the mode's first field: Your idea, Open the editor, or the idea's title.
 * - Keeps what was typed: closing only hides the sheet.
 * - Sets `has-sheet` on body while open, and keeps the button's aria-expanded current.
 * - Clears the Ask the team error line as a new request starts (the page writes a refusal there).
 * - editorUrl(base): Open the editor's address, composer:compose with the date, time and account the
 *   sheet was opened with (only those, only when given); opening from the button carries none.
 */
(function () {
  'use strict';

  var MODES = ['team', 'self', 'idea'];
  var HASH = '#new-post';
  var TRIGGER = '[aria-controls="new-post-sheet"]';
  var FIRST_FIELD = {
    team: '[data-testid="new-post-team-idea"]',
    self: '[data-testid="new-post-self-open"]',
    idea: '[data-testid="idea-title"]',
  };
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  /** What Open the editor carries, as the composer reads it, in the order a channel slot's own link has. */
  var EDITOR_FIELDS = [['account', 'account'], ['scheduled_date', 'date'], ['scheduled_time', 'time']];

  function visible(element) {
    return !!(element && element.getClientRects && element.getClientRects().length);
  }

  window.newPostSheet = function newPostSheet() {
    // The component's own element. In a handler, Alpine's `this.$el` is the element the expression sits
    // on (the mode button, the close button), so the sheet keeps its root from init.
    var root = null;
    return {
      sheetOpen: false,
      sheetMode: 'team',
      /** What the opener passed along (a Calendar cell's date, time and account), for Write it myself. */
      sheetContext: {},
      opener: null,

      init: function () {
        var sheet = this;
        root = this.$el;
        window.addEventListener('new-post:open', function (event) {
          sheet.open(event.detail || {}, event.target);
        });
        window.addEventListener('hashchange', function () {
          if (window.location.hash === HASH) sheet.open({});
        });
        root.addEventListener('htmx:beforeRequest', function (event) {
          var form = event.target && event.target.closest && event.target.closest('[data-testid="new-post-team"]');
          var error = form && form.querySelector('#new-post-team-error');
          if (error) error.textContent = '';
        });
        if (window.location.hash === HASH) this.$nextTick(function () { sheet.open({}); });
      },

      open: function (detail, source) {
        detail = detail || {};
        // The phone drawer is a modal with its own focus trap: close it first (base.html's shell scope).
        this.mobileMenuOpen = false;
        if (!this.sheetOpen) {
          var element = source && source.nodeType === 1 ? source : document.activeElement;
          this.opener = element && element !== document.body ? element : null;
        }
        this.sheetMode = MODES.indexOf(detail.mode) >= 0 ? detail.mode : 'team';
        this.sheetContext = { date: detail.date || '', time: detail.time || '', account: detail.account || '' };
        this.sheetOpen = true;
        document.body.classList.add('has-sheet');
        this.expanded(true);
        this.focusField();
      },

      close: function () {
        if (!this.sheetOpen) return;
        this.sheetOpen = false;
        document.body.classList.remove('has-sheet');
        this.expanded(false);
        if (window.location.hash === HASH && window.history && window.history.replaceState) {
          window.history.replaceState(null, '', window.location.pathname + window.location.search);
        }
        var opener = this.opener && document.contains(this.opener) ? this.opener : document.querySelector(TRIGGER);
        this.opener = null;
        this.$nextTick(function () {
          if (opener && typeof opener.focus === 'function') opener.focus();
          // A Calendar cell's "+" shows on hover only (calendar.html), so once the scrim lifts it may be
          // hidden again and cannot take focus: the New post button takes it instead of the page.
          var trigger = document.querySelector(TRIGGER);
          if (document.activeElement !== opener && trigger && trigger !== opener) trigger.focus();
        });
      },

      setMode: function (mode) {
        if (MODES.indexOf(mode) < 0) return;
        this.sheetMode = mode;
        this.focusField();
      },

      /** Open the editor's address: `base` (composer:compose) and what the sheet was opened with. */
      editorUrl: function (base) {
        var context = this.sheetContext || {};
        var params = new URLSearchParams();
        EDITOR_FIELDS.forEach(function (field) {
          if (context[field[1]]) params.set(field[0], context[field[1]]);
        });
        var query = params.toString();
        return query ? base + '?' + query : base;
      },

      expanded: function (value) {
        document.querySelectorAll(TRIGGER).forEach(function (trigger) {
          trigger.setAttribute('aria-expanded', value ? 'true' : 'false');
        });
      },

      /** Focus the mode's first field once the panel shows; else its first control; else Close. */
      focusField: function () {
        var mode = this.sheetMode;
        this.$nextTick(function () {
          if (!root) return;
          var panel = root.querySelector('[data-view="' + mode + '"]');
          var target = root.querySelector(FIRST_FIELD[mode]);
          if (!visible(target) && panel) {
            target = Array.prototype.find.call(panel.querySelectorAll(FOCUSABLE), visible) || null;
          }
          if (!visible(target)) target = root.querySelector('[data-testid="new-post-close"]');
          if (target) target.focus();
        });
      },
    };
  };
})();
