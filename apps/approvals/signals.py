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
@receiver(post_delete, sender="media_library.MediaAsset", dispatch_uid="approvals_revalidate_asset_deleted")
def _asset_saved(sender, instance, created=False, **kwargs):
    if created:
        return
    from django.db.models import Q

    from apps.composer.models import PlatformPost, PostMedia

    post_ids = set(PostMedia.objects.filter(media_asset=instance).values_list("post_id", flat=True))
    post_ids.update(
        PlatformPost.objects.filter(
            Q(platform_extra__thumbnail_asset_id=str(instance.pk))
            | Q(platform_extra__cover_image_asset_id=str(instance.pk))
        ).values_list("post_id", flat=True)
    )
    for post_id in post_ids:
        gate.schedule_revalidation(post_id)
