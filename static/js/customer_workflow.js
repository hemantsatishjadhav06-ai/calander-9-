/* Progressive enhancement only. Forms and links work without JavaScript. */
(() => {
    'use strict';

    const initialise = () => {
        const page = document.querySelector('[data-customer-workflow]');
        if (!page || page.dataset.workflowReady === 'true') return;
        page.dataset.workflowReady = 'true';

        const idea = page.querySelector('[data-workflow-create-form] textarea[name="idea"]');
        if (idea) {
            page.querySelectorAll('[data-workflow-prompt]').forEach(button => {
                button.hidden = false;
                button.addEventListener('click', () => {
                    if (idea.value.trim() && !window.confirm('Replace the idea you have already written?')) return;
                    idea.value = button.dataset.workflowPrompt;
                    idea.dispatchEvent(new Event('input', { bubbles: true }));
                    idea.focus();
                });
            });
        }

        // Ordinary navigation submits remain native; the disabled state only
        // prevents an accidental second click while the first POST is pending.
        page.addEventListener('submit', event => {
            const form = event.target;
            if (!form.matches('[data-workflow-create-form], [data-workflow-resume-form]')) return;
            if (!form.checkValidity()) return;
            if (form.dataset.submitting === 'true') {
                event.preventDefault();
                return;
            }
            form.dataset.submitting = 'true';
            form.querySelectorAll('button[type="submit"]').forEach(button => {
                button.disabled = true;
                button.setAttribute('aria-busy', 'true');
            });
        });

        const resetSubmission = () => {
            page.querySelectorAll('[data-submitting="true"]').forEach(form => {
                delete form.dataset.submitting;
                form.querySelectorAll('button[type="submit"]').forEach(button => {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                });
            });
        };
        window.addEventListener('pageshow', resetSubmission);

        const status = page.querySelector('[data-workflow-poll-status]');
        const refreshNote = page.querySelector('[data-workflow-refresh-note]');
        const updateButton = page.querySelector('[data-workflow-apply-updates]');
        let list = page.querySelector('#workflow-journeys');
        if (!list || !status || !refreshNote || !updateButton || !window.fetch) return;

        let endpoint;
        try {
            endpoint = new URL(page.dataset.workflowStatusUrl, window.location.href);
            if (endpoint.origin !== window.location.origin) return;
        } catch (_error) { return; }
        const staticNote = page.querySelector('[data-workflow-static-note]');
        if (staticNote) staticNote.hidden = true;

        let pendingList = null;
        let timer = null;
        let inFlight = false;
        let stopped = false;
        let controller = null;
        let failures = 0;
        const interval = 30000;

        const reading = () => {
            const selected = window.getSelection();
            return list.contains(document.activeElement) || (selected && !selected.isCollapsed && list.contains(selected.anchorNode));
        };
        const signature = fragment => {
            const copy = fragment.cloneNode(true);
            // Expanded disclosures and Django's newly masked CSRF token are
            // not new post activity. Neither should announce an update.
            copy.querySelectorAll('details[data-workflow-details]').forEach(item => item.removeAttribute('open'));
            copy.querySelectorAll('input[name="csrfmiddlewaretoken"]').forEach(item => item.setAttribute('value', ''));
            return copy.outerHTML;
        };
        const apply = replacement => {
            const openDetails = new Set(Array.from(list.querySelectorAll('details[open][data-workflow-details]'), item => item.dataset.workflowDetails));
            replacement.querySelectorAll('details[data-workflow-details]').forEach(item => {
                item.open = openDetails.has(item.dataset.workflowDetails);
            });
            list.replaceWith(replacement);
            list = replacement;
            pendingList = null;
            updateButton.hidden = true;
            status.textContent = 'Post progress updated.';
        };
        updateButton.addEventListener('click', () => {
            if (!pendingList) return;
            apply(pendingList);
            // The update trigger is about to become hidden. Put focus on a
            // stable heading, never a newly enabled approval control.
            const heading = page.querySelector('#cw-activity-heading');
            if (heading) {
                heading.setAttribute('tabindex', '-1');
                heading.focus();
            }
        });

        const schedule = () => {
            clearTimeout(timer);
            if (!stopped && list.dataset.active === 'true' && !document.hidden) timer = setTimeout(poll, interval);
        };
        const fail = permanent => {
            failures += 1;
            if (permanent || failures >= 3) {
                stopped = true;
                refreshNote.hidden = false;
                status.textContent = 'Automatic progress updates are paused.';
            }
        };
        const parseList = html => {
            if (typeof html !== 'string' || html.length > 300000) throw new Error('Invalid progress response');
            const template = document.createElement('template');
            template.innerHTML = html.trim();
            if (template.content.children.length !== 1) throw new Error('Invalid progress response');
            const replacement = template.content.firstElementChild;
            if (replacement.id !== 'workflow-journeys' || replacement.dataset.workspace !== page.dataset.workflowWorkspace) throw new Error('Invalid progress response');
            // Only our server-rendered journey fragment belongs in this view.
            if (replacement.querySelector('script, iframe, object, embed, style, link, base')) throw new Error('Invalid progress response');
            for (const element of [replacement, ...replacement.querySelectorAll('*')]) {
                for (const attribute of element.attributes) {
                    if (/^on/i.test(attribute.name)) throw new Error('Invalid progress response');
                    if (['href', 'action', 'src'].includes(attribute.name)) {
                        const target = new URL(attribute.value, endpoint.href);
                        if (!['https:', 'http:'].includes(target.protocol)) throw new Error('Invalid progress response');
                        if (attribute.name === 'action' && target.origin !== window.location.origin) throw new Error('Invalid progress response');
                    }
                }
            }
            return replacement;
        };

        const poll = async () => {
            if (stopped || inFlight || document.hidden || list.dataset.active !== 'true') return;
            inFlight = true;
            controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 12000);
            try {
                const response = await fetch(endpoint.href, { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal });
                if (response.status === 401 || response.status === 403 || response.redirected) {
                    fail(true);
                    return;
                }
                if (!response.ok || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Progress is unavailable');
                const payload = await response.json();
                const replacement = parseList(payload.html);
                const polling = typeof payload.polling === 'boolean' ? payload.polling : payload.active;
                if (typeof polling !== 'boolean' || replacement.dataset.active !== String(polling)) throw new Error('Invalid progress response');
                failures = 0;
                if (signature(replacement) !== signature(list)) {
                    if (reading() || page.querySelector('[data-submitting="true"]')) {
                        if (pendingList && signature(pendingList) === signature(replacement)) return;
                        pendingList = replacement;
                        updateButton.hidden = false;
                        status.textContent = 'New post activity is available when you are ready.';
                    } else apply(replacement);
                }
            } catch (_error) {
                if (!document.hidden) fail(false);
            } finally {
                clearTimeout(timeout);
                inFlight = false;
                controller = null;
                schedule();
            }
        };
        document.addEventListener('visibilitychange', () => {
            clearTimeout(timer);
            if (document.hidden && controller) controller.abort();
            else schedule();
        });
        window.addEventListener('pagehide', () => {
            clearTimeout(timer);
            if (controller) controller.abort();
        });
        window.addEventListener('pageshow', schedule);
        schedule();
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialise, { once: true });
    else initialise();
})();
