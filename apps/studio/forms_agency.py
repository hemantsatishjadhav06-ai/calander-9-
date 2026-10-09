"""Forms for the agency's settings pages: autopilot, the house style, reference uploads.

Every choice a form offers is built from this workspace's own rows (its
connected accounts, its blog sites, its members who may approve), so a posted
id from another workspace simply isn't a valid choice.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms

from apps.blog.models import BlogSite
from apps.social_accounts.models import SocialAccount

from .forms import _FIELD, STUDIO_PLATFORMS
from .models import AgencySettings

WEEKDAYS = (
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
)
MAX_PILLARS = 8
#: Reference pictures one upload may carry.
MAX_REFERENCE_FILES = 6
_CHECK = "w-4 h-4 rounded accent-orange-700"


def eligible_leads(workspace) -> list:
    """Members whose name autopilot drafts may carry: active, create and approve posts, not a client."""
    from apps.members.models import WorkspaceMembership

    people = []
    memberships = (
        WorkspaceMembership.objects.filter(workspace=workspace, user__is_active=True)
        .select_related("user", "custom_role")
        .order_by("user__name", "user__email")
    )
    for membership in memberships:
        if membership.workspace_role == WorkspaceMembership.WorkspaceRole.CLIENT and membership.custom_role is None:
            continue
        perms = membership.effective_permissions
        if perms.get("create_posts") and perms.get("approve_posts"):
            people.append((membership.user, membership.get_workspace_role_display()))
    return people


class PillarsField(forms.CharField):
    """Content pillars typed one per line or separated by commas."""

    def to_python(self, value):
        text = super().to_python(value) or ""
        pillars: list[str] = []
        for raw in text.replace(",", "\n").splitlines():
            pillar = " ".join(raw.split())[:60]
            if pillar and pillar.lower() not in {p.lower() for p in pillars}:
                pillars.append(pillar)
        return pillars

    def validate(self, value):
        if len(value) > MAX_PILLARS:
            raise forms.ValidationError(f"Keep it to {MAX_PILLARS} pillars or fewer, so each gets airtime.")

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(str(v) for v in value)
        return value


class AgencySettingsForm(forms.ModelForm):
    posts_per_week = forms.TypedChoiceField(
        label="Posts per week",
        coerce=int,
        choices=[(n, f"{n} post{'s' if n != 1 else ''}") for n in range(1, 15)],
        widget=forms.Select(attrs={"class": _FIELD}),
    )
    accounts = forms.ModelMultipleChoiceField(
        label="Accounts",
        queryset=SocialAccount.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": _CHECK}),
    )
    pillars = PillarsField(
        label="Content pillars",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 4, "class": _FIELD, "placeholder": "Explainers\nProjects\nBuyer questions\nFestive"}
        ),
    )
    plan_weekday = forms.TypedChoiceField(
        label="Plan on", coerce=int, choices=WEEKDAYS, widget=forms.Select(attrs={"class": _FIELD})
    )
    plan_hour = forms.TypedChoiceField(
        label="At",
        coerce=int,
        choices=[(h, f"{h:02d}:00") for h in range(24)],
        widget=forms.Select(attrs={"class": _FIELD}),
    )
    blog_posts_per_month = forms.TypedChoiceField(
        label="Blog articles per month",
        coerce=int,
        choices=[(0, "None")] + [(n, f"{n} article{'s' if n != 1 else ''}") for n in range(1, 9)],
        widget=forms.Select(attrs={"class": _FIELD}),
    )
    blog_site = forms.ModelChoiceField(
        label="Website",
        queryset=BlogSite.objects.none(),
        required=False,
        empty_label="Choose a website",
        widget=forms.Select(),
    )
    monthly_budget_usd = forms.DecimalField(
        label="Monthly AI budget (US$)",
        min_value=Decimal("1"),
        max_value=Decimal("10000"),
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": _FIELD, "step": "1", "inputmode": "decimal"}),
    )
    lead = forms.ChoiceField(label="Send drafts in the name of", required=False, widget=forms.Select())

    class Meta:
        model = AgencySettings
        fields = [
            "autopilot_enabled",
            "posts_per_week",
            "accounts",
            "pillars",
            "plan_weekday",
            "plan_hour",
            "blog_posts_per_month",
            "blog_site",
            "monthly_budget_usd",
            "lead",
            "learn_from_best",
            "inbox_drafts_enabled",
        ]
        labels = {
            "autopilot_enabled": "Autopilot",
            "learn_from_best": "Start from your best work",
            "inbox_drafts_enabled": "Draft replies to comments, messages and reviews",
        }
        widgets = {
            "autopilot_enabled": forms.CheckboxInput(attrs={"class": _CHECK}),
            "learn_from_best": forms.CheckboxInput(attrs={"class": _CHECK}),
            "inbox_drafts_enabled": forms.CheckboxInput(attrs={"class": _CHECK}),
        }

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["accounts"].queryset = SocialAccount.objects.filter(
            workspace=workspace, platform__in=STUDIO_PLATFORMS
        ).order_by("platform", "account_name")
        self.fields["accounts"].label_from_instance = lambda a: (
            f"{a.get_platform_display()} — {a.account_name or a.account_handle}"
            + (" (needs reconnecting)" if a.needs_reconnect else "")
        )
        self.fields["blog_site"].queryset = BlogSite.objects.filter(workspace=workspace, is_enabled=True).order_by(
            "name"
        )
        self.fields["blog_site"].widget.attrs["class"] = _FIELD
        self.lead_objects = {str(user.pk): user for user, _role in eligible_leads(workspace)}
        self.fields["lead"].choices = [("", "Choose an owner or manager")] + [
            (str(user.pk), f"{user.name or user.email} ({role.lower()})") for user, role in eligible_leads(workspace)
        ]
        self.fields["lead"].widget.attrs["class"] = _FIELD
        self.initial["lead"] = str(self.instance.lead_id or "")

    def clean_lead(self):
        value = self.cleaned_data.get("lead") or ""
        if value and value not in self.lead_objects:
            raise forms.ValidationError("Choose an owner or manager of this workspace.")
        return self.lead_objects.get(value)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("blog_posts_per_month") and not cleaned.get("blog_site"):
            self.add_error("blog_site", "Choose the website the articles are for, or set articles to None.")
        if cleaned.get("autopilot_enabled"):
            if not cleaned.get("accounts"):
                self.add_error("accounts", "Choose at least one account for the planned posts.")
            if not cleaned.get("lead"):
                self.add_error("lead", "Choose whose name the drafts carry: an owner or manager.")
        return cleaned

    def save(self, commit=True):
        row = super().save(commit=False)
        row.lead = self.cleaned_data.get("lead")
        if commit:
            row.save()
            self.save_m2m()
        return row


class HouseStyleForm(forms.Form):
    house_style = forms.CharField(
        label="Your house style",
        required=False,
        max_length=1500,
        widget=forms.Textarea(attrs={"rows": 4, "class": _FIELD}),
        help_text="A few lines on the look of your best work: light, palette, composition, what to avoid.",
    )


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleImageInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, list | tuple) else ([data] if data else [])
        if not files:
            raise forms.ValidationError("Choose at least one picture.")
        if len(files) > MAX_REFERENCE_FILES:
            raise forms.ValidationError(f"Upload up to {MAX_REFERENCE_FILES} pictures at a time.")
        return [super(MultipleImageField, self).clean(file, initial) for file in files]


class ReferenceUploadForm(forms.Form):
    images = MultipleImageField(label="Pictures by your best designer")
    note = forms.CharField(
        label="What to learn from them (optional)",
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={"class": _FIELD, "placeholder": "e.g. The warm dusk light and the calm layout"}),
    )
