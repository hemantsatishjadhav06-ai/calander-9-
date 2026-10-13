from django.contrib import admin

from .models import AgentRun, BrandProfile, StudioBrief, StudioConcept


@admin.register(BrandProfile)
class BrandProfileAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "workspace", "display_font", "default_template", "updated_at")
    search_fields = ("brand_name", "workspace__name")
    raw_id_fields = ("workspace", "logo")


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
