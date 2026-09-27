"""Accessibility sweep (audit gaps F2, F4, F7, F8).

Renders the main app pages as a logged-in owner and checks the rendered HTML:

- F2: every modal is a labelled ``role="dialog"`` with a focus trap, and the
  Alpine Focus plugin (which provides ``x-trap``) loads before Alpine itself.
- F4: no visible copy is set in ``text-stone-300`` / ``text-stone-400``
  (~1.5:1 / ~2.5:1 on white); those greys are reserved for icons, borders and
  disabled controls.
- F7: every visible form control has an accessible name.
- F8: every button and link has an accessible name (not just an SVG icon).
"""

import re
from html.parser import HTMLParser

from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import ContentCategory
from apps.inbox.models import SavedReply
from apps.media_library.models import MediaFolder
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
NAME_ATTRS = ("aria-label", ":aria-label", "x-bind:aria-label", "aria-labelledby")


def _owner():
    user = User.objects.create_user(email="o@example.com", password="pw", name="O", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    OrgMembership.objects.create(user=user, organization=org, org_role="owner")
    WorkspaceMembership.objects.create(user=user, workspace=ws, workspace_role="owner")
    return user, org, ws


class _Audit(HTMLParser):
    """Collects a11y findings from one rendered page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # [tag, attrs, text_parts, named_child]
        self.svg_depth = 0
        self.label_depth = 0
        self.ids = set()
        self.label_fors = set()
        self.unnamed_controls = []
        self.unnamed_buttons = []
        self.dialogs = []
        self.modal_wrappers = []  # (attrs, has_dialog_descendant)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_fors.add(a["for"])
        if tag == "svg":
            self.svg_depth += 1
        if a.get("role") == "dialog":
            self.dialogs.append(a)
            for entry in self.stack:
                if entry[0] == "wrapper":
                    entry[3] = True
        if tag in ("input", "select", "textarea"):
            self._check_control(tag, a)
        # a named descendant (x-text span, labelled img) names its button
        if self.stack and (
            any(k in a for k in ("x-text", "x-html")) or (tag == "img" and (a.get("alt") or a.get(":alt")))
        ):
            for entry in self.stack:
                if entry[0] in ("button", "a"):
                    entry[3] = True
        if tag in VOID:
            return
        cls = a.get("class") or ""
        is_wrapper = (
            "fixed" in cls.split() and "inset-0" in cls.split() and ("justify-center" in cls or "justify-end" in cls)
        ) or "idea-modal-overlay" in cls.split()
        self.stack.append(["wrapper" if is_wrapper else tag, a, [], False, tag])

    def handle_endtag(self, tag):
        if tag == "svg":
            self.svg_depth = max(0, self.svg_depth - 1)
        if tag == "label":
            self.label_depth = max(0, self.label_depth - 1)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][4] == tag:
                entry = self.stack[i]
                del self.stack[i:]
                self._close(entry)
                return

    def handle_data(self, data):
        if self.svg_depth or not data.strip():
            return
        for entry in self.stack:
            entry[2].append(data)

    def _close(self, entry):
        kind, a, text, named_child, tag = entry
        if kind == "wrapper":
            self.modal_wrappers.append((a, named_child or a.get("role") == "dialog"))
            return
        if tag == "button" or (tag == "a" and "href" in a):
            visible = "".join(text).replace("×", "").strip()
            if not (visible or named_child or any(k in a for k in NAME_ATTRS) or "x-text" in a):
                self.unnamed_buttons.append(a)

    def _check_control(self, tag, a):
        if tag == "input" and a.get("type", "text") in ("hidden", "submit", "button", "reset", "image"):
            return
        if a.get("aria-hidden") == "true" or "sr-only" in (a.get("class") or "").split():
            return
        if a.get("type") == "file" and (
            "hidden" in (a.get("class") or "").split() or "display:none" in (a.get("style") or "").replace(" ", "")
        ):
            return
        if any(k in a for k in NAME_ATTRS) or self.label_depth:
            return
        if a.get(":id"):  # bound id + bound :for inside an x-for loop
            return
        self.unnamed_controls.append(a)

    def finish(self):
        for a in self.unnamed_controls[:]:
            if a.get("id") in self.label_fors:
                self.unnamed_controls.remove(a)
        return self


# Opening tag whose static class list has a faint grey, immediately followed by text.
FAINT_TEXT = re.compile(
    r'<(\w+)(\s[^>]*?(?<=\s)class="[^"]*(?<![\w:-])text-stone-[34]00(?![\w-])[^"]*"[^>]*)>\s*([^<\s][^<]*)'
)


class A11ySweepTests(TestCase):
    def setUp(self):
        self.user, self.org, self.ws = _owner()
        # a second member so the member row renders its admin action menu
        other = User.objects.create_user(email="m@example.com", password="pw", name="M", tos_accepted_at=timezone.now())
        OrgMembership.objects.filter(user=other).delete()
        OrgMembership.objects.create(user=other, organization=self.org, org_role="member")
        ContentCategory.objects.create(workspace=self.ws, name="Educational")
        SavedReply.objects.create(workspace=self.ws, title="Thanks", body="Thanks {sender_name}!", created_by=self.user)
        MediaFolder.objects.create(organization=self.org, workspace=self.ws, name="Brand")
        self.client.force_login(self.user)

    def _pages(self):
        ws = {"workspace_id": self.ws.id}
        return {
            "calendar": reverse("calendar:calendar", kwargs=ws),
            "compose": reverse("composer:compose", kwargs=ws),
            "create": reverse("composer:create_landing", kwargs=ws),
            "categories": reverse("composer:category_list", kwargs=ws),
            "inbox": reverse("inbox:feed", kwargs=ws),
            "saved_replies": reverse("inbox:saved_replies", kwargs=ws),
            "media": reverse("media_library:index", kwargs=ws),
            "members": reverse("members:list"),
        }

    def _render(self, name, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, f"{name}: {url}")
        return response.content.decode()

    def test_pages_have_no_faint_copy(self):
        for name, url in self._pages().items():
            html = self._render(name, url)
            offenders = []
            for m in FAINT_TEXT.finditer(html):
                attrs, text = m.group(2), m.group(3).strip()
                if 'aria-disabled="true"' in attrs or text in ("&bull;", "•", "·"):
                    continue  # inactive controls and decorative separators are exempt
                offenders.append(f"<{m.group(1)}> {text[:40]!r}")
            with self.subTest(page=name):
                self.assertEqual(offenders, [], f"{name}: text in text-stone-300/400")

    def test_buttons_and_links_have_accessible_names(self):
        for name, url in self._pages().items():
            audit = _Audit()
            audit.feed(self._render(name, url))
            with self.subTest(page=name):
                self.assertEqual(
                    [
                        {k: v for k, v in a.items() if k in ("class", "@click", "href", "title")}
                        for a in audit.unnamed_buttons
                    ],
                    [],
                    f"{name}: icon-only buttons/links need an aria-label",
                )

    def test_form_controls_have_accessible_names(self):
        for name, url in self._pages().items():
            audit = _Audit()
            audit.feed(self._render(name, url))
            audit.finish()
            with self.subTest(page=name):
                self.assertEqual(
                    [
                        {k: v for k, v in a.items() if k in ("name", "id", "type", "placeholder", "x-model")}
                        for a in audit.unnamed_controls
                    ],
                    [],
                    f"{name}: form controls need a label, for/id pair or aria-label",
                )

    def test_every_modal_is_a_labelled_trapped_dialog(self):
        seen = 0
        for name, url in self._pages().items():
            audit = _Audit()
            html = self._render(name, url)
            audit.feed(html)
            with self.subTest(page=name):
                for attrs, has_dialog in audit.modal_wrappers:
                    self.assertTrue(has_dialog, f"{name}: modal overlay without role=dialog: {attrs.get('x-show')}")
                for d in audit.dialogs:
                    seen += 1
                    self.assertEqual(d.get("aria-modal"), "true", f"{name}: {d}")
                    self.assertTrue(any(k.startswith("x-trap") for k in d), f"{name}: dialog without x-trap: {d}")
                    labelled_by = d.get("aria-labelledby")
                    self.assertTrue(labelled_by or d.get("aria-label"), f"{name}: unlabelled dialog: {d}")
                    if labelled_by:
                        self.assertIn(labelled_by, audit.ids, f"{name}: aria-labelledby points nowhere")
                for tag in re.findall(r"<[^>]*aria-modal=\"true\"[^>]*>", html):
                    self.assertIn('role="dialog"', tag)
        self.assertGreater(seen, 10, "expected the modals on these pages to be marked up as dialogs")

    def test_focus_plugin_loads_before_alpine(self):
        html = self._render("calendar", self._pages()["calendar"])
        focus = html.find("js/vendor/alpine-focus.min.js")
        alpine = html.find("js/alpine.min.js")
        self.assertGreater(focus, -1, "Alpine Focus plugin (x-trap) is not loaded")
        self.assertLess(focus, alpine, "the Focus plugin must register before Alpine starts")
        # the client portal has its own layout that also loads Alpine
        with open(get_template("client_portal/portal_base.html").origin.name) as fh:
            portal = fh.read()
        self.assertLess(portal.find("alpine-focus.min.js"), portal.find("js/alpine.min.js"))
        self.assertGreater(portal.find("alpine-focus.min.js"), -1)
