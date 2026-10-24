"""``AgencySettings.features``: the per-workspace feature switches.

- A new row starts with no switches set.
- The previous release's INSERTs don't name the new column (invariant 8).
- Until Settings has a screen for them, staff set switches in the Django admin.
- The admin saves an empty box as no switches and refuses anything but known
  keys with true or false, as a form error.
- The admin page lists no other organisation's accounts.
"""

from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.features import FEATURE_KEYS, feature_enabled
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace


def _user(email):
    user = User.objects.create_user(email=email, password="pw", name="u", tos_accepted_at=timezone.now())
    auto = list(OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True))
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto).delete()
    return user


class FeaturesFieldTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")

    def test_a_new_row_has_no_switches(self):
        settings = AgencySettings.objects.create(workspace=self.ws)
        settings.refresh_from_db()
        self.assertEqual(settings.features, {})


class RollbackSafeColumnsTests(TestCase):
    """The previous release's INSERTs don't name the new column."""

    def test_old_style_inserts_still_work(self):
        org = Organization.objects.create(name="Org")
        ws = Workspace.objects.create(organization=org, name="WS")
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO studio_agency_settings (id, workspace_id, autopilot_enabled, creation_mode,"
                " posts_per_week, pillars, plan_weekday, plan_hour, blog_posts_per_month, monthly_budget_usd,"
                " learn_from_best, inbox_drafts_enabled, created_at, updated_at)"
                " VALUES (gen_random_uuid(), %s, false, 'confirm', 5, '[]', 4, 16, 0, 150, false, false, now(), now())",
                [ws.id],
            )
            cursor.execute("SELECT features = '{}'::jsonb FROM studio_agency_settings WHERE workspace_id = %s", [ws.id])
            self.assertIs(cursor.fetchone()[0], True)
        self.assertEqual(AgencySettings.objects.get(workspace=ws).features, {})


class FeaturesAdminTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.other = Workspace.objects.create(organization=self.org, name="Other")
        self.settings = AgencySettings.objects.create(workspace=self.ws)
        AgencySettings.objects.create(workspace=self.other)
        root = _user("root@example.com")
        root.is_staff = True
        root.is_superuser = True
        root.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(root)
        self.url = reverse("admin:studio_agencysettings_change", args=[self.settings.pk])

    def test_the_change_page_renders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="features"')

    def _save(self, features, pillars="[]"):
        return self.client.post(
            self.url,
            {
                "workspace": self.ws.pk,
                "creation_mode": AgencySettings.CreationMode.CONFIRM,
                "posts_per_week": 5,
                "pillars": pillars,
                "plan_weekday": 4,
                "plan_hour": 16,
                "blog_posts_per_month": 0,
                "monthly_budget_usd": "150.00",
                "features": features,
            },
        )

    def test_saving_a_switch_turns_it_on_for_that_workspace_only(self):
        response = self._save('{"queues": true}')
        self.assertEqual(response.status_code, 302)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.features, {"queues": True})
        self.assertIs(feature_enabled(self.ws, "queues"), True)
        self.assertIs(feature_enabled(self.other, "queues"), False)

    def test_an_empty_box_or_null_saves_no_switches(self):
        for features in ("", "null"):
            with self.subTest(features=features):
                AgencySettings.objects.filter(pk=self.settings.pk).update(features={"queues": True})
                response = self._save(features)
                self.assertEqual(response.status_code, 302)
                self.settings.refresh_from_db()
                self.assertEqual(self.settings.features, {})

    def test_an_empty_pillars_box_saves_no_pillars(self):
        # The same NOT NULL column trap as features: an empty box or null is None to the form.
        for pillars in ("", "null"):
            with self.subTest(pillars=pillars):
                AgencySettings.objects.filter(pk=self.settings.pk).update(pillars=["Launches"])
                response = self._save("{}", pillars=pillars)
                self.assertEqual(response.status_code, 302)
                self.settings.refresh_from_db()
                self.assertEqual(self.settings.pillars, [])

    def test_anything_but_known_keys_with_booleans_is_a_form_error(self):
        AgencySettings.objects.filter(pk=self.settings.pk).update(features={"queues": True})
        for features in ("[]", '{"blgo": true}', '{"queues": "yes"}'):
            with self.subTest(features=features):
                response = self._save(features)
                self.assertEqual(response.status_code, 200)
                errors = response.context["adminform"].form.errors["features"]
                self.assertIn(", ".join(FEATURE_KEYS), errors[0])
                self.settings.refresh_from_db()
                self.assertEqual(self.settings.features, {"queues": True})

    def test_the_error_names_the_wrong_key_or_value(self):
        response = self._save('{"blgo": true, "queues": "yes"}')
        self.assertEqual(response.status_code, 200)
        message = response.context["adminform"].form.errors["features"][0]
        self.assertIn("blgo", message)
        self.assertIn("queues", message)

    def test_the_workspace_cannot_be_changed_on_an_existing_row(self):
        # Moving the row would carry one workspace's settings to another.
        response = self.client.get(self.url)
        self.assertNotContains(response, 'name="workspace"')
        self.client.post(self.url, {"workspace": self.other.pk, "features": "{}"})
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.workspace_id, self.ws.pk)

    def test_the_change_page_lists_no_other_organisations_accounts(self):
        # Page size and noise: the raw-id field lists no accounts at all.
        foreign_org = Organization.objects.create(name="Foreign")
        foreign_ws = Workspace.objects.create(organization=foreign_org, name="Foreign WS")
        SocialAccount.objects.create(
            workspace=foreign_ws, platform="linkedin_company", account_platform_id="9", account_name="Foreign Page"
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Foreign Page")
