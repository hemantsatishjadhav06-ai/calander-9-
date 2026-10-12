/* Keep an agency conversation usable while HTMX replaces its messages or panel.
 * State lives only in this page: no draft text, evidence or consent is persisted.
 */
(function () {
    "use strict";

    if (window.agencyThreadStateLoaded) return;
    window.agencyThreadStateLoaded = true;

    const PANEL = "[data-agency-thread]";
    const LOG = "[data-thread-log]";
    const COMPOSER = "[data-thread-composer]";
    const DECISION = "form[data-thread-decision]";
    const choices = ["target_brief_id", "reference_id", "style_mode"];
    const requests = new WeakMap();
    const initializedLogs = new WeakSet();
    const unreadCounts = new WeakMap();

    function panelOf(element) {
        return element && element.closest ? element.closest(PANEL) : null;
    }

    function identity(panel) {
        return panel.dataset.threadKey || panel.id;
    }

    function field(form, name) {
        return form ? form.elements.namedItem(name) : null;
    }

    function filesSignature(input) {
        return input && input.files
            ? Array.from(input.files, file => [file.name, file.size, file.lastModified, file.type].join(":")).join("\n")
            : "";
    }

    function nearBottom(log) {
        return log.scrollHeight - log.clientHeight - log.scrollTop < 40;
    }

    function messageIds(log) {
        return log ? Array.from(log.querySelectorAll("[data-thread-message-id]"), el => el.dataset.threadMessageId) : [];
    }

    function receiptSnapshot(panel) {
        const receipts = new Map();
        panel.querySelectorAll("[data-platform-receipt][data-receipt-status]").forEach(row => {
            receipts.set(row.dataset.platformReceipt, {
                status: row.dataset.receiptStatus,
                account: row.dataset.receiptAccount || "Posting destination",
                nativeId: row.dataset.receiptNativeId || "",
            });
        });
        return receipts;
    }

    function detailsKey(details, panel) {
        if (details.dataset.threadDetailsKey) return details.dataset.threadDetailsKey;
        const card = details.closest("[data-creative-brief]");
        const draft = details.closest("[data-thread-draft]");
        const scope = card || draft || details.closest(COMPOSER);
        if (!scope) return null;
        const prefix = card ? "brief:" + card.dataset.creativeBrief : draft ? "draft:" + draft.dataset.threadDraft : "composer";
        return prefix + ":" + Array.from(scope.querySelectorAll("details")).indexOf(details);
    }

    function briefFingerprint(form) {
        const card = form.closest("[data-creative-brief]");
        return card ? card.textContent.replace(/\s+/g, " ").trim() : "";
    }

    function decisionGuard(form) {
        if (!form || !form.matches(DECISION)) return null;
        const attempt = field(form, "expected_attempt_id");
        const fingerprint = field(form, "expected_fingerprint");
        const destination = form.dataset.decisionDestination;
        if (!form.dataset.threadDecision || !attempt || !fingerprint || !attempt.value || !fingerprint.value || !destination) return null;
        return JSON.stringify([form.dataset.threadDecision, attempt.value, fingerprint.value, destination]);
    }

    function detailsDecisionGuards(details) {
        const forms = Array.from(details.querySelectorAll(DECISION));
        if (!forms.length) return null;
        const guards = forms.map(decisionGuard);
        return guards.every(Boolean) ? JSON.stringify(guards) : false;
    }

    function decisionSnapshot(form) {
        const guard = decisionGuard(form);
        if (!guard) return null;
        const values = {};
        ["native_post_id", "url", "native_post_url", "reason"].forEach(name => {
            const input = field(form, name);
            if (input && input.type !== "hidden") values[name] = input.value;
        });
        const checkbox = field(form, "confirmed");
        return { guard: guard, values: values, checked: checkbox && checkbox.type === "checkbox" ? checkbox.checked : null };
    }

    function focusSnapshot(panel) {
        const active = document.activeElement;
        if (!active || !panel.contains(active)) return null;
        const confirm = active.closest("[data-confirm-brief]");
        const decision = active.closest(DECISION);
        const card = active.closest("[data-creative-brief]");
        const message = active.closest("[data-thread-message-id]");
        const composer = active.closest(COMPOSER);
        const details = active.closest("details");
        const scope = decision || confirm || card || message || composer || panel;
        return {
            id: active.id,
            name: active.getAttribute("name"),
            tag: active.tagName,
            confirmation: confirm && confirm.dataset.confirmBrief,
            decision: decision && decision.dataset.threadDecision,
            decisionGuard: decisionGuard(decision),
            brief: card && card.dataset.creativeBrief,
            message: message && message.dataset.threadMessageId,
            composer: !!composer,
            details: details && detailsKey(details, panel),
            detailsGuard: details ? detailsDecisionGuards(details) : null,
            tagIndex: Array.from(scope.querySelectorAll(active.tagName)).indexOf(active),
            selectionStart: typeof active.selectionStart === "number" ? active.selectionStart : null,
            selectionEnd: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
        };
    }

    function composerSnapshot(panel) {
        const form = panel.querySelector(COMPOSER);
        if (!form) return null;
        const result = { values: {}, currentChoices: {}, file: field(form, "reference_upload") };
        choices.concat(["body"]).forEach(name => {
            const input = field(form, name);
            if (input) {
                result.values[name] = input.value;
                if (input.hasAttribute("data-current-choice")) result.currentChoices[name] = input.dataset.currentChoice;
            }
        });
        const internal = field(form, "is_internal");
        result.internal = internal ? internal.checked : false;
        result.fileSignature = filesSignature(result.file);
        return result;
    }

    function snapshot(panel) {
        const log = panel.querySelector(LOG);
        const details = new Map();
        panel.querySelectorAll("details").forEach(element => {
            const key = detailsKey(element, panel);
            const guards = detailsDecisionGuards(element);
            if (key && guards !== false) details.set(key, { open: element.open, decisions: guards });
        });
        const confirmations = new Map();
        panel.querySelectorAll("[data-confirm-brief]").forEach(form => {
            const checkbox = field(form, "facts_confirmed");
            const message = field(form, "confirmation_message_id");
            if (checkbox && message && message.value === form.dataset.confirmBrief) {
                confirmations.set(form.dataset.confirmBrief, {
                    checked: checkbox.checked,
                    fingerprint: briefFingerprint(form),
                });
            }
        });
        const decisions = new Map();
        panel.querySelectorAll(DECISION).forEach(form => {
            const state = decisionSnapshot(form);
            if (state) decisions.set(form.dataset.threadDecision, state);
        });
        return {
            id: panel.id,
            key: identity(panel),
            composer: composerSnapshot(panel),
            focus: focusSnapshot(panel),
            details: details,
            confirmations: confirmations,
            decisions: decisions,
            receipts: receiptSnapshot(panel),
            log: log ? { top: log.scrollTop, bottom: nearBottom(log), ids: messageIds(log) } : null,
            unread: unreadCounts.get(panel) || 0,
        };
    }

    function setUnread(panel, count) {
        unreadCounts.set(panel, count);
        const button = panel.querySelector("[data-thread-new-messages]");
        if (!button) return;
        button.hidden = count === 0;
        button.classList.toggle("hidden", count === 0);
        button.textContent = count === 1 ? "1 new message — show latest" : count + " new messages — show latest";
    }

    function announce(panel, count, previousReceipts) {
        const status = panel.querySelector("[data-thread-announcement]");
        if (!status) return;
        const announcements = [];
        if (count) {
            const total = messageIds(panel.querySelector(LOG)).length;
            const addition = count === 1 ? "A new message is available in this thread." : count + " new messages are available in this thread.";
            // Changing the total also makes consecutive one-message arrivals
            // distinct live-region updates for assistive technology.
            announcements.push(addition + " " + total + " messages in this thread.");
        }
        const currentReceipts = receiptSnapshot(panel);
        const changed = [];
        currentReceipts.forEach((receipt, id) => {
            const previous = previousReceipts.get(id);
            if (!previous || previous.status !== receipt.status || previous.nativeId !== receipt.nativeId) {
                changed.push(receipt.account + ": " + receipt.status + (receipt.nativeId ? "; post ID recorded." : "."));
            }
        });
        if (changed.length) {
            announcements.push("Posting status updated. " + changed.slice(0, 3).join(" "));
            if (changed.length > 3) announcements.push((changed.length - 3) + " other destinations updated.");
        }
        if (currentReceipts.size !== previousReceipts.size) {
            announcements.push(currentReceipts.size + " posting destinations shown.");
        }
        if (announcements.length) status.textContent = announcements.join(" ");
    }

    function restoreComposer(panel, previous, submitted, sentSuccessfully) {
        const form = panel.querySelector(COMPOSER);
        if (!form || !previous) return;
        choices.forEach(name => {
            const input = field(form, name);
            const value = previous.values[name];
            const serverContext = name !== "target_brief_id" && input && input.hasAttribute("data-current-choice");
            const wasChanged = value !== previous.currentChoices[name];
            const wasCommitted = sentSuccessfully && submitted && value === submitted.values[name];
            if (serverContext && (!wasChanged || wasCommitted)) return;
            // A removed account, draft or reference must not be reintroduced.
            if (input && value !== undefined && Array.from(input.options).some(option => option.value === value)) {
                input.value = value;
            }
        });
        const body = field(form, "body");
        if (body && previous.values.body !== undefined) {
            const unchangedSinceSend = submitted && previous.values.body === submitted.values.body;
            body.value = sentSuccessfully && unchangedSinceSend ? "" : previous.values.body;
        }
        const internal = field(form, "is_internal");
        if (internal) internal.checked = previous.internal;
        const freshFile = field(form, "reference_upload");
        const fileChanged = submitted && previous.fileSignature !== submitted.fileSignature;
        if (freshFile && freshFile !== previous.file && previous.file && previous.fileSignature && (!sentSuccessfully || fileChanged)) {
            // Browsers prohibit assigning FileList. Reuse the selected input node
            // after an error, preserving its new permission/validation attributes.
            // Changing a file input's type would erase its browser-owned FileList.
            Array.from(previous.file.attributes).forEach(attr => {
                if (attr.name !== "type" && attr.name !== "value" && !freshFile.hasAttribute(attr.name)) previous.file.removeAttribute(attr.name);
            });
            Array.from(freshFile.attributes).forEach(attr => {
                if (attr.name !== "type" && attr.name !== "value") previous.file.setAttribute(attr.name, attr.value);
            });
            freshFile.replaceWith(previous.file);
        }
    }

    function restoreFocus(panel, previous) {
        if (!previous) return;
        let scope = panel;
        if (previous.decision) {
            scope = Array.from(panel.querySelectorAll(DECISION))
                .find(form => form.dataset.threadDecision === previous.decision);
            if (!scope || !previous.decisionGuard || decisionGuard(scope) !== previous.decisionGuard) return;
        } else if (previous.confirmation) {
            scope = Array.from(panel.querySelectorAll("[data-confirm-brief]"))
                .find(form => form.dataset.confirmBrief === previous.confirmation);
        } else if (previous.brief) {
            scope = Array.from(panel.querySelectorAll("[data-creative-brief]"))
                .find(card => card.dataset.creativeBrief === previous.brief);
        } else if (previous.message) {
            scope = Array.from(panel.querySelectorAll("[data-thread-message-id]"))
                .find(message => message.dataset.threadMessageId === previous.message);
        } else if (previous.composer) {
            scope = panel.querySelector(COMPOSER) || panel;
        }
        if (!scope) return;
        if (previous.detailsGuard !== null) {
            const details = Array.from(panel.querySelectorAll("details"))
                .find(element => detailsKey(element, panel) === previous.details);
            if (!details || !previous.detailsGuard || detailsDecisionGuards(details) !== previous.detailsGuard) return;
        }
        let target = previous.id ? document.getElementById(previous.id) : null;
        if (target && !scope.contains(target)) target = null;
        if (!target && previous.name) {
            target = Array.from(scope.querySelectorAll("[name]"))
                .find(element => element.getAttribute("name") === previous.name && element.tagName === previous.tag);
        }
        if (!target && previous.details) {
            const details = Array.from(scope.querySelectorAll("details"))
                .find(element => detailsKey(element, panel) === previous.details);
            if (details && previous.tag === "SUMMARY") target = details.querySelector("summary");
        }
        if (!target && previous.tagIndex >= 0) target = scope.querySelectorAll(previous.tag)[previous.tagIndex];
        if (!target || target.disabled) return;
        // If focus moved elsewhere during the request, leave it there.
        const active = document.activeElement;
        if (active && active !== document.body && active !== target && active.isConnected) return;
        target.focus({ preventScroll: true });
        if (previous.selectionStart !== null && typeof target.setSelectionRange === "function") {
            try { target.setSelectionRange(previous.selectionStart, previous.selectionEnd); } catch (_) { /* Not a text input. */ }
        }
    }

    function initialize(panel, preserveScroll) {
        const log = panel.querySelector(LOG);
        if (!log || initializedLogs.has(log)) return;
        initializedLogs.add(log);
        // A separate persistent status announces additions, not the old transcript.
        log.setAttribute("aria-live", "off");
        if (!preserveScroll) log.scrollTop = log.scrollHeight;
        log.addEventListener("scroll", function () {
            if (nearBottom(log)) setUnread(panel, 0);
        }, { passive: true });
    }

    function restore(panel, saved, request) {
        if (identity(panel) !== saved.key) return;
        const failed = !!panel.querySelector("[data-thread-error]") || request.status >= 400;
        const ownSend = request.composer && !failed;
        restoreComposer(panel, saved.composer, request.composer, !!ownSend);
        panel.querySelectorAll("details").forEach(element => {
            const key = detailsKey(element, panel);
            const previous = key && saved.details.get(key);
            if (previous && previous.decisions === detailsDecisionGuards(element)) element.open = previous.open;
        });
        panel.querySelectorAll("[data-confirm-brief]").forEach(form => {
            const previous = saved.confirmations.get(form.dataset.confirmBrief);
            const checkbox = field(form, "facts_confirmed");
            const message = field(form, "confirmation_message_id");
            // Consent belongs only to this unchanged summary message. It never
            // carries to a new summary and never creates approval or a submission.
            if (previous && checkbox && message && message.value === form.dataset.confirmBrief
                    && previous.fingerprint === briefFingerprint(form)) {
                checkbox.checked = previous.checked;
            }
        });
        panel.querySelectorAll(DECISION).forEach(form => {
            const previous = saved.decisions.get(form.dataset.threadDecision);
            if (!previous || decisionGuard(form) !== previous.guard) return;
            Object.entries(previous.values).forEach(([name, value]) => {
                const input = field(form, name);
                if (input && input.type !== "hidden" && !input.disabled) input.value = value;
            });
            const checkbox = field(form, "confirmed");
            if (previous.checked !== null && checkbox && checkbox.type === "checkbox" && !checkbox.disabled) {
                checkbox.checked = previous.checked;
            }
        });
        const log = panel.querySelector(LOG);
        initialize(panel, true);
        if (log && saved.log) {
            const oldIds = new Set(saved.log.ids);
            const newCount = messageIds(log).filter(id => !oldIds.has(id)).length;
            const bottom = saved.log.bottom || (request.sentForm && !failed);
            log.scrollTop = bottom ? log.scrollHeight : saved.log.top;
            setUnread(panel, bottom ? 0 : saved.unread + newCount);
            announce(panel, newCount, saved.receipts);
        }
        restoreFocus(panel, saved.focus);
    }

    document.addEventListener("htmx:beforeRequest", function (event) {
        const detail = event.detail;
        const panel = panelOf(detail.elt);
        if (!panel || !detail.xhr) return;
        const form = detail.elt.closest("form");
        requests.set(detail.xhr, {
            composer: form && form.matches(COMPOSER) ? composerSnapshot(panel) : null,
            sentForm: !!form,
        });
    });

    function omitUnchangedDirection(form, parameters) {
        if (!form || !form.matches(COMPOSER)) return;
        ["reference_id", "style_mode"].forEach(name => {
            const input = field(form, name);
            if (input && input.hasAttribute("data-current-choice") && input.value === input.dataset.currentChoice) {
                if (typeof parameters.delete === "function") parameters.delete(name);
                else delete parameters[name];
            }
        });
    }

    // Keep selectors visible without treating an unchanged reference/style as a
    // fresh mutation. This also covers ordinary submissions without HTMX.
    document.addEventListener("formdata", function (event) {
        omitUnchangedDirection(event.target, event.formData);
    }, true);
    document.addEventListener("htmx:configRequest", function (event) {
        const form = event.detail.elt.closest("form");
        omitUnchangedDirection(form, event.detail.parameters);
    });

    document.addEventListener("htmx:beforeSwap", function (event) {
        const detail = event.detail;
        const panel = panelOf(detail.target);
        if (!panel || !detail.xhr || !detail.shouldSwap) return;
        const request = requests.get(detail.xhr) || {};
        request.snapshot = snapshot(panel);
        request.status = detail.xhr.status;
        requests.set(detail.xhr, request);
    });

    document.addEventListener("htmx:afterSwap", function (event) {
        const request = requests.get(event.detail.xhr);
        if (!request || !request.snapshot) return;
        const panel = document.getElementById(request.snapshot.id);
        if (panel && panel.matches(PANEL)) restore(panel, request.snapshot, request);
    });

    document.addEventListener("htmx:load", function (event) {
        const target = event.detail.elt;
        const parent = panelOf(target);
        if (parent) initialize(parent, true);
        if (target.querySelectorAll) target.querySelectorAll(PANEL).forEach(panel => initialize(panel, true));
    });

    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-thread-new-messages]");
        const panel = panelOf(button);
        if (!panel) return;
        const log = panel.querySelector(LOG);
        if (log) {
            log.scrollTop = log.scrollHeight;
            if (!log.hasAttribute("tabindex")) log.setAttribute("tabindex", "-1");
            log.focus({ preventScroll: true });
        }
        setUnread(panel, 0);
    });

    function start() {
        document.querySelectorAll(PANEL).forEach(panel => initialize(panel, false));
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
}());
