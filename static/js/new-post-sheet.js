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
 * - Puts focus in the mode's first field: Your idea, Open the editor, or the idea's title, once the dialog
 *   shows (opened as the page loads, it waits a few frames for x-show). Opened from
 *   the open phone drawer (new-post:open or #new-post while it is open), the field takes focus back
 *   once when the drawer's trap returns it to the drawer's button as it lets go.
 * - Keeps what was typed: closing only hides the sheet.
 * - Sets `has-sheet` on body while open, and keeps the button's aria-expanded current.
 * - Clears the Ask the team error line as a new request starts (the page writes a refusal there).
 * - editorUrl(base): Open the editor's address, composer:compose with the date, time and account the
 *   sheet was opened with (only those, only when given); opening from the button carries none.
 *
 * Save it as an idea (T18; templates/composer/partials/new_post_idea.html), moved here from the shell's
 * New idea dialog (base.html's window.ideaModalHelpers and sidebarNewMenu(), gone with T19):
 * - The columns and tags come from the page's json_script elements (#new-post-idea-columns,
 *   #new-post-idea-tags; the tags only with the templates switch), never pasted into code.
 * - Pictures go up one by one to the form's data-upload-url and are sent as asset ids; a new tag goes to
 *   its data-tag-url. The emoji picker's 95 choices are rendered only while it is open (_filteredEmojis)
 *   and an emoji goes into the sheet's own description, at the caret or over what is selected.
 * - saveIdea posts the form to composer:idea_create. On success it fires ideaChanged, empties the idea
 *   form and closes the sheet (Ask the team's words stay); a refusal, a refused picture or a missing
 *   security token shows in the form's own error line (ideaError), never in a toast or a browser alert.
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
  var IDEA_FORM = '[data-testid="new-post-idea"]';
  /** How long, after opening from the phone drawer, the field may take back the focus the drawer returns. */
  var DRAWER_HANDBACK_MS = 300;
  /** How many frames the field waits for the dialog to show before it settles for what shows. */
  var SHOW_FRAMES = 10;
  var SAVE_FAILED = 'Could not save the idea. Please try again.';
  var UPLOAD_FAILED = 'One of the files failed to upload. Please try again.';
  var TOKEN_MISSING = 'Security token missing. Please reload the page.';
  /** The idea form's emoji picker: 95 choices, each with the words its search matches. */
  var EMOJIS = [
    {e:'😀',n:'grinning'},{e:'😃',n:'smiley'},{e:'😄',n:'smile'},{e:'😁',n:'grin'},{e:'😆',n:'laughing'},
    {e:'😅',n:'sweat smile'},{e:'🤣',n:'rofl'},{e:'😂',n:'joy'},{e:'🙂',n:'slight smile'},{e:'😊',n:'blush'},
    {e:'😇',n:'innocent'},{e:'🥰',n:'love'},{e:'😍',n:'heart eyes'},{e:'🤩',n:'star struck'},{e:'😘',n:'kiss'},
    {e:'😜',n:'wink tongue'},{e:'🤔',n:'thinking'},{e:'🤗',n:'hugging'},{e:'🤫',n:'shushing'},{e:'😎',n:'cool'},
    {e:'🥳',n:'party'},{e:'😤',n:'triumph'},{e:'😱',n:'scream'},{e:'🥺',n:'pleading'},{e:'😢',n:'cry'},
    {e:'👍',n:'thumbs up'},{e:'👎',n:'thumbs down'},{e:'👏',n:'clap'},{e:'🙌',n:'raised hands'},{e:'🤝',n:'handshake'},
    {e:'💪',n:'strong'},{e:'✌️',n:'peace'},{e:'🤞',n:'crossed fingers'},{e:'👋',n:'wave'},{e:'🫡',n:'salute'},
    {e:'❤️',n:'red heart'},{e:'🧡',n:'orange heart'},{e:'💛',n:'yellow heart'},{e:'💚',n:'green heart'},{e:'💙',n:'blue heart'},
    {e:'💜',n:'purple heart'},{e:'🖤',n:'black heart'},{e:'🤍',n:'white heart'},{e:'💯',n:'hundred'},{e:'💥',n:'boom'},
    {e:'⭐',n:'star'},{e:'🌟',n:'glowing star'},{e:'✨',n:'sparkles'},{e:'⚡',n:'lightning'},{e:'🔥',n:'fire'},
    {e:'🎉',n:'party popper'},{e:'🎊',n:'confetti'},{e:'🏆',n:'trophy'},{e:'🎯',n:'bullseye'},{e:'🚀',n:'rocket'},
    {e:'💡',n:'light bulb'},{e:'📌',n:'pin'},{e:'📎',n:'paperclip'},{e:'📝',n:'memo'},{e:'✏️',n:'pencil'},
    {e:'✅',n:'check mark'},{e:'❌',n:'cross mark'},{e:'⚠️',n:'warning'},{e:'❓',n:'question'},{e:'❗',n:'exclamation'},
    {e:'💬',n:'speech'},{e:'👀',n:'eyes'},{e:'🎨',n:'art'},{e:'📸',n:'camera'},{e:'🎬',n:'clapper'},
    {e:'📱',n:'phone'},{e:'💻',n:'laptop'},{e:'📊',n:'chart'},{e:'📈',n:'trending up'},{e:'📅',n:'calendar'},
    {e:'⏰',n:'alarm clock'},{e:'🔗',n:'link'},{e:'🔒',n:'lock'},{e:'🏷️',n:'label'},{e:'📣',n:'megaphone'},
    {e:'🌍',n:'globe'},{e:'☀️',n:'sun'},{e:'🌙',n:'moon'},{e:'🌈',n:'rainbow'},{e:'🍕',n:'pizza'},
    {e:'☕',n:'coffee'},{e:'🍺',n:'beer'},{e:'🎵',n:'music'},{e:'🐶',n:'dog'},{e:'🐱',n:'cat'},
    {e:'✍️',n:'writing'},{e:'🧠',n:'brain'},{e:'💎',n:'gem'},{e:'🪄',n:'magic wand'},{e:'🎁',n:'gift'},
  ];

  function visible(element) {
    return !!(element && element.getClientRects && element.getClientRects().length);
  }

  /** A json_script element's value under `root` (Django escapes <, > and & in it), or [] when absent. */
  function readJsonList(root, id) {
    var element = root && root.querySelector('script[id="' + id + '"]');
    if (!element) return [];
    try {
      var value = JSON.parse(element.textContent || '[]');
      return Array.isArray(value) ? value : [];
    } catch (error) {
      return [];
    }
  }

  /**
   * The idea form's requests (base.html's window.ideaModalHelpers, moved here; T19 removed that copy).
   * They answer with the server's words instead of a toast or a browser alert.
   */
  var ideaModalHelpers = {
    mediaAssetIdsCsv: function (items) {
      return (items || []).map(function (item) { return item.asset_id; }).join(',');
    },
    appendUploadedMedia: function (items, data, file) {
      if (!items || !data || !data.asset_id) return;
      var exists = items.some(function (item) { return item.asset_id === data.asset_id; });
      if (exists) return;
      items.push({
        asset_id: data.asset_id,
        url: data.url || '',
        filename: data.filename || (file && file.name) || '',
        media_type: data.media_type || ((file && file.type && file.type.indexOf('video/') === 0) ? 'video' : 'image'),
      });
    },
    /** The form's own token, else the page's, else the cookie's. */
    getCsrfToken: function (form) {
      var input = (form && form.querySelector('[name=csrfmiddlewaretoken]')) || document.querySelector('[name=csrfmiddlewaretoken]');
      if (input && input.value) return input.value;
      var cookieMatch = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
      return cookieMatch ? decodeURIComponent(cookieMatch[1]) : '';
    },
    triggerIdeaChanged: function () {
      if (window.htmx && typeof window.htmx.trigger === 'function') {
        window.htmx.trigger(document.body, 'ideaChanged');
        return;
      }
      document.body.dispatchEvent(new CustomEvent('ideaChanged', { bubbles: true }));
    },
    /** The server's reason as plain text (a missing title, a refused file), from a text or JSON body. */
    refusal: function (text, fallback) {
      var reason = (new DOMParser().parseFromString(text || '', 'text/html').body.textContent || '').trim();
      if (reason.charAt(0) === '{') {
        try {
          var json = JSON.parse(reason);
          reason = json.error || Object.values(json.errors || {}).flat().join(' ');
        } catch (error) { /* keep the text as it came */ }
      }
      return reason || fallback;
    },
    /** POST the idea form to its action: {ok: true} after ideaChanged, or {ok: false, message}. */
    submitIdeaForm: function (form) {
      var helpers = this;
      var url = form && form.getAttribute('action');
      if (!url) return Promise.resolve({ ok: false, message: SAVE_FAILED });
      var token = helpers.getCsrfToken(form);
      if (!token) return Promise.resolve({ ok: false, message: TOKEN_MISSING });
      return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': token }, body: new FormData(form) })
        .then(function (response) {
          if (response.ok) {
            helpers.triggerIdeaChanged();
            return { ok: true, message: '' };
          }
          return response.text()
            .catch(function () { return ''; })
            .then(function (text) { return { ok: false, message: helpers.refusal(text, SAVE_FAILED) }; });
        })
        .catch(function () { return { ok: false, message: SAVE_FAILED }; });
    },
    /** Upload one file; resolves with {asset_id, url, filename, media_type}, rejects with a userMessage. */
    uploadIdeaMediaAsset: function (uploadUrl, file, token) {
      if (!uploadUrl || !token) {
        var refused = new Error('upload_refused');
        refused.userMessage = token ? UPLOAD_FAILED : TOKEN_MISSING;
        return Promise.reject(refused);
      }
      var formData = new FormData();
      formData.append('file', file);
      return fetch(uploadUrl, { method: 'POST', headers: { 'X-CSRFToken': token }, body: formData })
        .then(function (response) {
          if (!response.ok) {
            // A 400 names why the file was refused (wrong type, too large, quota).
            return response.json().catch(function () { return {}; }).then(function (data) {
              var failed = new Error('upload_failed');
              failed.userMessage = data && data.error;
              throw failed;
            });
          }
          return response.json();
        })
        .then(function (data) {
          if (!data || !data.asset_id) throw new Error('upload_failed');
          return data;
        });
    },
  };

  window.newPostSheet = function newPostSheet() {
    // The component's own element. In a handler, Alpine's `this.$el` is the element the expression sits
    // on (the mode button, the close button), so the sheet keeps its root from init.
    var root = null;
    // The frames focusField has waited for the dialog to show (see there).
    var waited = 0;
    return {
      sheetOpen: false,
      sheetMode: 'team',
      /** What the opener passed along (a Calendar cell's date, time and account), for Write it myself. */
      sheetContext: {},
      opener: null,

      // Save it as an idea: the idea form's state (its title and description stay in their fields).
      ideaColumns: [],
      ideaAllTags: [],
      ideaGroup: '',
      ideaTags: [],
      ideaTagSearch: '',
      ideaTagsOpen: false,
      tagDialogOpen: false,
      newTagName: '',
      ideaMedia: [],
      ideaUploads: 0,
      ideaSaving: false,
      ideaDragOver: false,
      ideaError: '',
      emojiPickerOpen: false,
      _emojiSearch: '',
      _emojiList: EMOJIS,

      init: function () {
        var sheet = this;
        root = this.$el;
        this.ideaColumns = readJsonList(root, 'new-post-idea-columns');
        this.ideaAllTags = readJsonList(root, 'new-post-idea-tags');
        this.ideaGroup = this.defaultIdeaGroup();
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
        var fromDrawer = !!this.mobileMenuOpen;
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
        this.focusField(fromDrawer);
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

      // ── Save it as an idea ──────────────────────────────────────────────────────────────────────

      /** The first column of the board (what the shell's dialog chose), or none when there is none. */
      defaultIdeaGroup: function () {
        return this.ideaColumns.length ? String(this.ideaColumns[0].id) : '';
      },

      ideaMediaIds: function () {
        return ideaModalHelpers.mediaAssetIdsCsv(this.ideaMedia);
      },

      ideaPrimaryMediaId: function () {
        return this.ideaMedia.length ? this.ideaMedia[0].asset_id : '';
      },

      toggleIdeaTag: function (tag) {
        var index = this.ideaTags.indexOf(tag);
        if (index === -1) this.ideaTags.push(tag);
        else this.ideaTags.splice(index, 1);
      },

      ideaTagMatches: function () {
        var query = (this.ideaTagSearch || '').toLowerCase().trim();
        return this.ideaAllTags.filter(function (tag) { return !query || tag.toLowerCase().indexOf(query) >= 0; });
      },

      /** Enter in the tag search: create what was typed when it is new, else choose the one match. */
      ideaTagEnter: function () {
        var name = (this.ideaTagSearch || '').trim();
        var matches = this.ideaTagMatches();
        if (name && this.ideaAllTags.indexOf(name) < 0) {
          this.addIdeaTag(name);
        } else if (matches.length === 1) {
          this.toggleIdeaTag(matches[0]);
          this.ideaTagSearch = '';
        }
      },

      /** Choose a tag, adding it to the workspace's tags (through the form's tag address) when it is new. */
      addIdeaTag: function (name) {
        name = (name || '').trim();
        if (!name) return;
        if (this.ideaAllTags.indexOf(name) < 0) {
          this.ideaAllTags.push(name);
          this.ideaAllTags.sort();
        }
        if (this.ideaTags.indexOf(name) < 0) this.ideaTags.push(name);
        this.ideaTagSearch = '';
        this._persistTag(name);
      },

      openTagDialog: function () {
        this.newTagName = (this.ideaTagSearch || '').trim();
        this.ideaTagSearch = '';
        this.tagDialogOpen = true;
      },

      closeTagDialog: function () {
        this.tagDialogOpen = false;
        this.newTagName = '';
      },

      createTagFromDialog: function () {
        var name = (this.newTagName || '').trim();
        if (!name) return;
        this.addIdeaTag(name);
        this.closeTagDialog();
      },

      /** Save a new tag at once; saving the idea keeps its tags too, so a failure here loses nothing. */
      _persistTag: function (name) {
        var form = root && root.querySelector(IDEA_FORM);
        var url = form && form.getAttribute('data-tag-url');
        var token = ideaModalHelpers.getCsrfToken(form);
        if (!url || !token) return;
        fetch(url, {
          method: 'POST',
          headers: { 'X-CSRFToken': token, 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'name=' + encodeURIComponent(name),
        }).catch(function () { /* the idea's own save keeps the tag */ });
      },

      // The emoji picker: no choices while it is closed, so a closed picker renders no buttons.
      _filteredEmojis: function () {
        if (!this.emojiPickerOpen) return [];
        var q = (this._emojiSearch || '').toLowerCase().trim();
        if (!q) return this._emojiList;
        return this._emojiList.filter(function (em) { return em.n.includes(q); });
      },

      /** Put an emoji in the sheet's own description, at the caret or over what is selected. */
      _insertEmoji: function (emoji) {
        var description = root && root.querySelector('[data-testid="idea-description"]');
        if (description) {
          var start = description.selectionStart;
          var end = description.selectionEnd;
          description.value = description.value.substring(0, start) + emoji + description.value.substring(end);
          description.selectionStart = description.selectionEnd = start + emoji.length;
          description.focus();
          description.dispatchEvent(new Event('input', { bubbles: true }));
        }
        this._emojiSearch = '';
      },

      pickIdeaFiles: function (event) {
        var input = event.target;
        var files = Array.prototype.slice.call(input.files || []);
        input.value = '';
        return this._enqueueMediaFiles(files);
      },

      dropIdeaFiles: function (event) {
        return this._enqueueMediaFiles(event.dataTransfer ? event.dataTransfer.files : []);
      },

      _enqueueMediaFiles: function (fileList) {
        var sheet = this;
        return Promise.all(Array.prototype.slice.call(fileList || []).map(function (file) {
          return sheet._uploadIdeaMediaAsset(file);
        }));
      },

      _uploadIdeaMediaAsset: function (file) {
        if (!file) return Promise.resolve(false);
        var sheet = this;
        var form = root && root.querySelector(IDEA_FORM);
        sheet.ideaUploads += 1;
        sheet.ideaError = '';
        return ideaModalHelpers
          .uploadIdeaMediaAsset(form && form.getAttribute('data-upload-url'), file, ideaModalHelpers.getCsrfToken(form))
          .then(function (data) {
            ideaModalHelpers.appendUploadedMedia(sheet.ideaMedia, data, file);
            return true;
          })
          .catch(function (error) {
            sheet.ideaError = (error && error.userMessage) || UPLOAD_FAILED;
            return false;
          })
          .then(function (uploaded) {
            sheet.ideaUploads = Math.max(0, sheet.ideaUploads - 1);
            return uploaded;
          });
      },

      removeIdeaMedia: function (index) {
        if (index < 0 || index >= this.ideaMedia.length) return;
        this.ideaMedia.splice(index, 1);
      },

      /** Save idea: nothing is sent while a picture is still going up or a save is under way. */
      saveIdea: function (event) {
        var form = event && event.target;
        if (!form || this.ideaUploads > 0 || this.ideaSaving) return Promise.resolve(false);
        var sheet = this;
        sheet.ideaSaving = true;
        sheet.ideaError = '';
        return ideaModalHelpers.submitIdeaForm(form).then(function (result) {
          sheet.ideaSaving = false;
          if (!result.ok) {
            sheet.ideaError = result.message;
            return false;
          }
          sheet.resetIdea(form);
          sheet.close();
          return true;
        });
      },

      /** Empty the idea form once its idea is saved; Ask the team's words are left alone. */
      resetIdea: function (form) {
        if (form && typeof form.reset === 'function') form.reset();
        this.ideaGroup = this.defaultIdeaGroup();
        this.ideaTags = [];
        this.ideaTagSearch = '';
        this.ideaTagsOpen = false;
        this.ideaMedia = [];
        this.ideaError = '';
        this.emojiPickerOpen = false;
        this._emojiSearch = '';
        this.closeTagDialog();
      },

      expanded: function (value) {
        document.querySelectorAll(TRIGGER).forEach(function (trigger) {
          trigger.setAttribute('aria-expanded', value ? 'true' : 'false');
        });
      },

      /**
       * Focus the mode's first field once the panel shows; else its first control; else Close.
       * `afterDrawer`: the sheet was opened while the phone drawer was open (new-post:open, #new-post).
       * The drawer's trap hands focus back to its button as it lets go, and that can land just after this
       * (the sheet's own trap starts a moment later and never pulls focus in), so the field takes it back
       * once, if it comes while the sheet is still opening.
       */
      focusField: function (afterDrawer) {
        var sheet = this;
        var mode = this.sheetMode;
        this.$nextTick(function () {
          if (!root) return;
          // The dialog, or the mode's panel, may not show yet: Alpine's x-show shows on the next frame,
          // and this runs from $nextTick, a timer, which WebKit runs before that frame. That happens when
          // the sheet opens as the page loads (#new-post, where `n` lands away from the sheet:
          // shortcuts.js) and on every switch of mode (CI's iPhone 13, WebKit, put the focus on Close
          // after Save it as an idea and Write it myself). Try again on the next frames, then settle
          // for what shows.
          var dialog = root.querySelector('[data-testid="new-post-sheet"]');
          var panel = root.querySelector('[data-view="' + mode + '"]');
          var target = root.querySelector(FIRST_FIELD[mode]);
          var panelShows = visible(target) || !!(panel && Array.prototype.some.call(panel.querySelectorAll(FOCUSABLE), visible));
          var shows = (!dialog || visible(dialog)) && panelShows;
          if (!shows && waited < SHOW_FRAMES && typeof window.requestAnimationFrame === 'function') {
            waited += 1;
            window.requestAnimationFrame(function () {
              if (sheet.sheetOpen && sheet.sheetMode === mode) sheet.focusField(afterDrawer);
              else waited = 0;
            });
            return;
          }
          waited = 0;
          if (!visible(target) && panel) {
            target = Array.prototype.find.call(panel.querySelectorAll(FOCUSABLE), visible) || null;
          }
          if (!visible(target)) target = root.querySelector('[data-testid="new-post-close"]');
          if (!target) return;
          target.focus();
          if (afterDrawer) sheet._reclaimFocus(target);
        });
      },

      /** Give `target` focus back once if it leaves the sheet within DRAWER_HANDBACK_MS (see focusField). */
      _reclaimFocus: function (target) {
        var sheet = this;
        var timer = null;
        function stop() {
          document.removeEventListener('focusin', reclaim, true);
          clearTimeout(timer);
        }
        function reclaim(event) {
          stop();
          if (sheet.sheetOpen && root && !root.contains(event.target)) target.focus();
        }
        document.addEventListener('focusin', reclaim, true);
        timer = setTimeout(stop, DRAWER_HANDBACK_MS);
      },
    };
  };
})();
