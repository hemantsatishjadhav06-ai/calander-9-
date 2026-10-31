"""The Request invite form.

Everything here is typed by a stranger, so it is treated as untrusted text: it is
stored and shown to platform operators (escaped, never as a link) and goes
nowhere else. It never enters a prompt and never reaches Telegram.
"""

from django import forms


def _one_line(value: str) -> str:
    """Collapse runs of whitespace, so a name or agency cannot break a title or mail subject over lines."""
    return " ".join(value.split())


class RequestInviteForm(forms.Form):
    name = forms.CharField(label="Your name", max_length=120)
    agency = forms.CharField(label="Agency", max_length=160)
    email = forms.EmailField(label="Work email", max_length=254)
    note = forms.CharField(
        label="Anything we should know",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    # The honeypot. People never see it (the template hides it from them and from
    # assistive technology); form-filling bots tend to fill every field.
    website = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    AUTOCOMPLETE = {"name": "name", "agency": "organization", "email": "email", "note": "off"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, token in self.AUTOCOMPLETE.items():
            self.fields[name].widget.attrs.update({"class": "mk-input", "autocomplete": token})

    def clean_name(self) -> str:
        return _one_line(self.cleaned_data["name"])

    def clean_agency(self) -> str:
        return _one_line(self.cleaned_data["agency"])

    @property
    def is_bot(self) -> bool:
        return bool(self.data.get("website", "").strip())
