from django import forms
from django.core.exceptions import ValidationError

from . import trust
from .forms import _FIELD
from .models import BrandClaim


class BrandClaimForm(forms.ModelForm):
    confirmed = forms.BooleanField(label="I verified this exact claim against its source and set a review expiry.")

    class Meta:
        model = BrandClaim
        fields = ["category", "claim", "source_url", "source_note", "valid_until", "confirmed"]
        widgets = {"claim": forms.Textarea(attrs={"rows": 3}), "valid_until": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", _FIELD)

    def clean(self):
        data = super().clean()
        if not data.get("source_url") and not data.get("source_note"):
            raise ValidationError("Add a source URL or identify the owner-verified source document.")
        if data.get("valid_until") and data["valid_until"] < trust.local_date(self.workspace):
            self.add_error("valid_until", "Choose today or a future review expiry.")
        if data.get("source_url"):
            from urllib.parse import urlsplit

            parsed = urlsplit(data["source_url"])
            if parsed.username or parsed.password:
                self.add_error("source_url", "Use a public source URL without credentials.")
        return data
