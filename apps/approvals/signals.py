"""Re-check approvals when approved content changes.

Every write that can change what a channel publishes — the post's text, a
channel's overrides or format, the attached media, or an edit to a media file —
schedules :func:`apps.approvals.gate.revalidate_post` for when the write
commits. Revalidation is a no-op outside workspaces that require dashboard
approval.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import gate


@receiver(post_save, sender="composer.Post", dispatch_uid="approvals_revalidate_post")
def _post_saved(sender, instance, created, **kwargs):
    if not created:
        gate.schedule_revalidation(instance.pk)


@receiver(post_save, sender="composer.PlatformPost", dispatch_uid="approvals_revalidate_platform_post")
def _platform_post_saved(sender, instance, **kwargs):
    gate.record_time_approval_if_any(instance)
    gate.schedule_revalidation(instance.post_id)


@receiver(post_save, sender="composer.PostMedia", dispatch_uid="approvals_revalidate_media_saved")
@receiver(post_delete, sender="composer.PostMedia", dispatch_uid="approvals_revalidate_media_deleted")
def _post_media_changed(sender, instance, **kwargs):
    gate.schedule_revalidation(instance.post_id)


@receiver(post_save, sender="media_library.MediaAsset", dispatch_uid="approvals_revalidate_asset")
def _asset_saved(sender, instance, created, **kwargs):
    if created:
        return
    from apps.composer.models import PostMedia

    for post_id in PostMedia.objects.filter(media_asset=instance).values_list("post_id", flat=True).distinct():
        gate.schedule_revalidation(post_id)
