from django import forms
from django.contrib import admin

from apps.common.features import FEATURE_KEYS

from .models import AgencySettings, AgentRun, BrandProfile, StudioBrief, StudioConcept


@admin.register(BrandProfile)
class BrandProfileAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "workspace", "display_font", "default_template", "updated_at")
    search_fields = ("brand_name", "workspace__name")
    raw_id_fields = ("workspace", "logo")


class AgencySettingsAdminForm(forms.ModelForm):
    class Meta:
        model = AgencySettings
        fields = "__all__"

    def clean_features(self):
        """An empty box or ``null`` is no switches; anything else is known keys with true or false."""
        features = self.cleaned_data.get("features")
        if features is None:
            return {}
        keys = ", ".join(FEATURE_KEYS)
        if not isinstance(features, dict):
            raise forms.ValidationError(
                'Enter an object like {"queues": true}: the keys are %(keys)s, the values true or false.',
                params={"keys": keys},
            )
        wrong = [key for key, value in features.items() if key not in FEATURE_KEYS or not isinstance(value, bool)]
        if wrong:
            raise forms.ValidationError(
                "Not a known switch set to true or false: %(wrong)s. The keys are %(keys)s.",
                params={"wrong": ", ".join(wrong), "keys": keys},
            )
        return features

    def clean_pillars(self):
        """An empty box or ``null`` is no pillars (the column is NOT NULL)."""
        pillars = self.cleaned_data.get("pillars")
        return [] if pillars is None else pillars


@admin.register(AgencySettings)
class AgencySettingsAdmin(admin.ModelAdmin):
    form = AgencySettingsAdminForm
    list_display = ("workspace", "autopilot_enabled", "creation_mode")
    search_fields = ("workspace__name",)
    raw_id_fields = ("workspace", "lead", "backup", "blog_site", "accounts")

    def get_readonly_fields(self, request, obj=None):
        # Moving a row would carry one workspace's settings to another.
        return ("workspace",) if obj else ()


class StudioConceptInline(admin.TabularInline):
    model = StudioConcept
    extra = 0
    fields = ("revision", "position", "title", "post_format", "recommended")
    readonly_fields = fields
    can_delete = False


class AgentRunInline(admin.TabularInline):
    model = AgentRun
    extra = 0
    fields = ("revision", "agent", "status", "summary", "model", "input_tokens", "output_tokens", "duration_ms")
    readonly_fields = fields
    can_delete = False


@admin.register(StudioBrief)
class StudioBriefAdmin(admin.ModelAdmin):
    list_display = ("__str__", "workspace", "status", "stage", "revision", "author", "created_at")
    list_filter = ("status", "stage")
    search_fields = ("idea", "workspace__name")
    raw_id_fields = ("workspace", "author", "chosen_concept", "picture", "graphic", "post")
    readonly_fields = ("post_copy", "design_spec", "review_notes", "style_reference", "error")
    inlines = [StudioConceptInline, AgentRunInline]
