from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.onboarding"
    verbose_name = "Onboarding"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from apps.composer.models import Idea, PlatformPost, Post
        from apps.members.models import WorkspaceMembership
        from apps.social_accounts.models import SocialAccount

        # The checklist is cached per workspace (context_processors); drop it
        # when something it counts changes, so connecting a channel ticks the
        # box on the next page rather than up to a minute later. Status changes
        # made with queryset updates don't send signals; the short cache TTL
        # covers those.
        for model in (SocialAccount, Post, Idea, WorkspaceMembership):
            post_save.connect(
                _invalidate_for_workspace_row, sender=model, dispatch_uid=f"onboarding.inv.{model.__name__}"
            )
            post_delete.connect(
                _invalidate_for_workspace_row, sender=model, dispatch_uid=f"onboarding.invd.{model.__name__}"
            )
        post_save.connect(
            _invalidate_for_platform_post, sender=PlatformPost, dispatch_uid="onboarding.inv.PlatformPost"
        )


def _invalidate_for_workspace_row(sender, instance, **kwargs):
    from apps.onboarding.context_processors import invalidate_checklist

    workspace_id = getattr(instance, "workspace_id", None)
    if workspace_id:
        invalidate_checklist(workspace_id)


def _invalidate_for_platform_post(sender, instance, **kwargs):
    from apps.composer.models import Post
    from apps.onboarding.context_processors import invalidate_checklist

    workspace_id = Post.objects.filter(pk=instance.post_id).values_list("workspace_id", flat=True).first()
    if workspace_id:
        invalidate_checklist(workspace_id)
