"""Forms for the AI Studio pages."""

from __future__ import annotations

import datetime as dt
import zoneinfo

from django import forms

from .models import BrandProfile, StudioBrief

#: Networks the Studio designs for. LinkedIn first: the copy follows LinkedIn's
#: conventions; the others get the same graphic, with the short caption where
#: the full one is over their limit.
STUDIO_PLATFORMS = (
    "linkedin_company",
    "linkedin_personal",
    "facebook",
    "instagram",
    "instagram_login",
    "threads",
    "x",
    "bluesky",
    "mastodon",
)

_FIELD = (
    "w-full text-sm px-3 py-2.5 rounded-xl border border-stone-300 bg-white outline-none "
    "focus:border-orange-500 focus:ring-2 focus:ring-orange-100 transition-all"
)


def studio_accounts(workspace):
    from apps.social_accounts.models import SocialAccount

    order = {platform: index for index, platform in enumerate(STUDIO_PLATFORMS)}
    accounts = SocialAccount.objects.filter(workspace=workspace, platform__in=STUDIO_PLATFORMS)
    return sorted(accounts, key=lambda a: (order.get(a.platform, 99), (a.account_name or "").lower()))


class BriefForm(forms.Form):
    idea = forms.CharField(
        label="Your idea",
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": _FIELD,
                "placeholder": "e.g. Many buyers still don't know what a landlord's share is — explain it simply",
            }
        ),
    )
    notes = forms.CharField(
        label="Direction for the team (optional)",
        required=False,
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": _FIELD,
                "placeholder": "Facts to use, the tone, a link to include, anything to avoid…",
            }
        ),
    )
    goal = forms.ChoiceField(
        label="Goal",
        required=False,
        choices=[("", "Let the strategist decide"), *StudioBrief.Goal.choices],
        widget=forms.Select(attrs={"class": _FIELD}),
    )
    accounts = forms.MultipleChoiceField(
        label="Post to",
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "w-4 h-4 rounded accent-orange-700"}),
    )
    style_lock = forms.BooleanField(
        label="Match the look of the last post",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "mt-0.5 w-4 h-4 rounded accent-orange-700"}),
    )
    source_picture = forms.ChoiceField(label="Picture", required=False)

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.media_library.models import MediaAsset

        self.workspace = workspace
        self.account_objects = {str(a.pk): a for a in studio_accounts(workspace)}
        self.fields["accounts"].choices = [
            (pk, f"{a.account_name or a.account_handle} · {a.get_platform_display()}")
            for pk, a in self.account_objects.items()
        ]
        if not self.is_bound:
            linkedin = [pk for pk, a in self.account_objects.items() if a.platform.startswith("linkedin")]
            self.initial.setdefault("accounts", linkedin[:1] or list(self.account_objects)[:1])
        photos = (
            MediaAsset.objects.filter(workspace=workspace, media_type=MediaAsset.MediaType.IMAGE)
            .exclude(source__in=["ai-studio"])
            .order_by("-created_at")[:24]
        )
        self.photo_objects = {str(p.pk): p for p in photos}
        self.fields["source_picture"].choices = [("", "Generate a picture with AI")] + [
            (pk, f"Use “{(p.title or p.filename)[:60]}”") for pk, p in self.photo_objects.items()
        ]
        self.fields["source_picture"].widget.attrs["class"] = _FIELD

    def clean_accounts(self):
        chosen = [self.account_objects[pk] for pk in self.cleaned_data["accounts"] if pk in self.account_objects]
        if not chosen:
            raise forms.ValidationError("Choose at least one connected account.")
        broken = [a for a in chosen if a.needs_reconnect]
        if broken:
            names = ", ".join(a.account_name or a.get_platform_display() for a in broken)
            raise forms.ValidationError(f"Reconnect {names} first (Settings → Social accounts).")
        return chosen

    def clean_source_picture(self):
        value = self.cleaned_data.get("source_picture") or ""
        return self.photo_objects.get(value)


class FeedbackForm(forms.Form):
    feedback = forms.CharField(
        label="What should change?",
        max_length=4000,
        widget=forms.Textarea(
            attrs={"rows": 3, "class": _FIELD, "placeholder": "e.g. Shorter hook, and mention the documents checklist"}
        ),
    )
    new_picture = forms.BooleanField(
        label="Paint a new picture too",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "w-4 h-4 rounded accent-orange-700"}),
    )


class ScheduleForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": _FIELD}))
    time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time", "class": _FIELD}))

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace

    def aware_datetime(self) -> dt.datetime:
        try:
            zone = zoneinfo.ZoneInfo(self.workspace.effective_timezone or "UTC")
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            zone = zoneinfo.ZoneInfo("UTC")
        return dt.datetime.combine(self.cleaned_data["date"], self.cleaned_data["time"]).replace(tzinfo=zone)


class HashtagsField(forms.CharField):
    def to_python(self, value):
        text = super().to_python(value) or ""
        tags = []
        for raw in text.replace(",", " ").split():
            word = "".join(ch for ch in raw.lstrip("#") if ch.isalnum() or ch == "_")
            if word:
                tags.append(f"#{word}")
        return tags[:10]

    def prepare_value(self, value):
        if isinstance(value, list):
            return " ".join(value)
        return value


class BrandProfileForm(forms.ModelForm):
    hashtags = HashtagsField(
        required=False,
        widget=forms.TextInput(attrs={"class": _FIELD, "placeholder": "#LandlordShare #HyderabadRealEstate"}),
    )
    logo = forms.ChoiceField(required=False, label="Logo")

    class Meta:
        model = BrandProfile
        fields = [
            "brand_name",
            "about",
            "audience",
            "voice",
            "facts",
            "dos",
            "donts",
            "compliance",
            "default_cta",
            "website",
            "hashtags",
            "primary_color",
            "accent_color",
            "display_font",
            "wordmark",
            "domain",
            "photo_style",
            "default_template",
            "default_format",
            "default_grade",
        ]
        widgets = {
            "about": forms.Textarea(attrs={"rows": 2}),
            "audience": forms.Textarea(attrs={"rows": 3}),
            "voice": forms.Textarea(attrs={"rows": 3}),
            "facts": forms.Textarea(attrs={"rows": 10}),
            "dos": forms.Textarea(attrs={"rows": 2}),
            "donts": forms.Textarea(attrs={"rows": 2}),
            "compliance": forms.Textarea(attrs={"rows": 3}),
            "photo_style": forms.Textarea(attrs={"rows": 3}),
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "accent_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.media_library.models import MediaAsset

        logos = MediaAsset.objects.filter(
            workspace=self.instance.workspace, media_type=MediaAsset.MediaType.IMAGE
        ).order_by("-created_at")[:40]
        self.logo_objects = {str(asset.pk): asset for asset in logos}
        if self.instance.logo_id and str(self.instance.logo_id) not in self.logo_objects:
            self.logo_objects[str(self.instance.logo_id)] = self.instance.logo
        self.fields["logo"].choices = [("", "No logo — set the wordmark in type")] + [
            (pk, (asset.title or asset.filename)[:70]) for pk, asset in self.logo_objects.items()
        ]
        self.initial["logo"] = str(self.instance.logo_id or "")
        for name, field in self.fields.items():
            if name in ("primary_color", "accent_color"):
                field.widget.attrs["class"] = "h-10 w-16 rounded-lg border border-stone-300 bg-white p-1 cursor-pointer"
            else:
                field.widget.attrs.setdefault("class", _FIELD)

    def clean_logo(self):
        return self.logo_objects.get(self.cleaned_data.get("logo") or "")

    def clean_primary_color(self):
        return (self.cleaned_data.get("primary_color") or "").upper()

    def clean_accent_color(self):
        return (self.cleaned_data.get("accent_color") or "").upper()

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.logo = self.cleaned_data.get("logo")
        if commit:
            profile.save()
        return profile
