"""A compact form for confirmed campaign event totals."""

from django import forms
from django.utils import timezone

from . import outcomes
from .jobtypes.plan import zone_of
from .models import CampaignOutcome


class _PostChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.caption_snippet[:80]} · {str(obj.pk)[:8]}"


class OutcomeForm(forms.Form):
    campaign_name = forms.CharField(
        label="Campaign label", max_length=120, help_text="Use a campaign name, not a person's name or contact details."
    )
    occurred_on = forms.DateField(label="Date the outcome happened", widget=forms.DateInput(attrs={"type": "date"}))
    kind = forms.ChoiceField(label="Outcome", choices=CampaignOutcome.Kind.choices)
    count = forms.IntegerField(label="Confirmed events", min_value=1, max_value=1_000_000, initial=1)
    post = _PostChoice(
        label="Related approved or published post",
        queryset=None,
        required=False,
        empty_label="Campaign-level entry; no specific post attribution",
    )
    submission_token = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, workspace, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["post"].queryset = outcomes.eligible_posts(workspace)
        self.initial.setdefault("occurred_on", timezone.now().astimezone(zone_of(workspace)).date())
        self.initial.setdefault("submission_token", outcomes.submission_token(workspace, user))
        for name, field in self.fields.items():
            if name != "submission_token":
                field.widget.attrs["class"] = "w-full rounded-lg border border-ink-400 bg-white px-3 py-2 text-sm"

    def clean_occurred_on(self):
        value = self.cleaned_data["occurred_on"]
        if value > timezone.now().astimezone(zone_of(self.workspace)).date():
            raise forms.ValidationError(
                "Record an outcome that already happened; planned visits are not completed visits."
            )
        return value
