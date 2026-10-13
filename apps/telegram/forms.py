from django import forms

from .api import valid_token
from .models import TelegramChat


class ConnectForm(forms.Form):
    token = forms.CharField(
        label="BotFather token",
        max_length=200,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password", "class": "w-full rounded-lg border border-stone-300 p-3"},
        ),
    )
    approvals_enabled = forms.BooleanField(
        required=False, label="Allow paired internal approvers to approve exact review cards in Telegram"
    )

    def clean_token(self):
        token = self.cleaned_data["token"].strip()
        if not valid_token(token):
            raise forms.ValidationError("Enter the complete bot token from BotFather.")
        return token


class PairingForm(forms.Form):
    purpose = forms.ChoiceField(choices=[("user", "Pair my personal identity"), ("chat", "Pair a group")])
    audience = forms.ChoiceField(choices=TelegramChat.Audience.choices, initial="private")
    group_membership_confirmed = forms.BooleanField(
        required=False,
        label="I control this group's membership and checked that every viewer may see this audience's content",
    )

    def __init__(self, *args, group=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].widget = forms.HiddenInput()
        self.initial["purpose"] = "chat" if group else "user"
        self.fields["audience"].widget.attrs.update({"class": "w-full rounded-lg border border-stone-300 bg-white p-3"})
        if group:
            self.fields["audience"].choices = [
                choice for choice in TelegramChat.Audience.choices if choice[0] != TelegramChat.Audience.PRIVATE
            ]
            self.initial["audience"] = TelegramChat.Audience.CLIENT
        else:
            self.fields["audience"].widget = forms.HiddenInput()
            self.initial["audience"] = TelegramChat.Audience.PRIVATE

    def clean(self):
        values = super().clean() or {}
        if values.get("purpose") == "user" and values.get("audience") != TelegramChat.Audience.PRIVATE:
            self.add_error("audience", "Pair your own identity in the bot's private chat.")
        if values.get("purpose") == "chat" and values.get("audience") == TelegramChat.Audience.PRIVATE:
            self.add_error("audience", "Choose a client group or an internal team group.")
        if values.get("purpose") == "chat" and not values.get("group_membership_confirmed"):
            raise forms.ValidationError("Confirm the group membership boundary before issuing a group code.")
        return values


class ManagedBotCreationForm(forms.Form):
    manager_connection = forms.ChoiceField(
        label="Your personally linked manager bot",
        choices=[],
        widget=forms.Select(attrs={"class": "w-full rounded-lg border border-stone-300 bg-white p-3"}),
    )

    def __init__(self, *args, managers=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager_connection"].choices = [
            (str(manager.pk), f"@{manager.bot_username} · {manager.workspace.name}") for manager in managers
        ]
