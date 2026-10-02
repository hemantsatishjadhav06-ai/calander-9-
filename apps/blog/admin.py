from django.contrib import admin

from .models import BlogPost, BlogPostEvent, BlogSite


@admin.register(BlogSite)
class BlogSiteAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "kind", "repo", "branch", "workflow_file", "is_enabled")
    list_filter = ("kind", "is_enabled")
    search_fields = ("name", "repo", "site_url")


class BlogPostEventInline(admin.TabularInline):
    model = BlogPostEvent
    extra = 0
    can_delete = False
    fields = ("created_at", "action", "revision", "user", "detail")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    """Read-only: content and status change only through apps.blog.services,
    which keeps the revision, the approval and the audit trail consistent."""

    list_display = ("title", "site", "status", "revision", "approved_revision", "published_at")
    list_filter = ("status", "site")
    search_fields = ("title", "slug")
    inlines = [BlogPostEventInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
