"""Seed each brand's test drafts and proposed seven-day calendar. Idempotent.

Creates, once per brand, the social drafts in :mod:`apps.workspaces.brand_content`
(with the brand's own website imagery attached) and the blog drafts, and marks
each in ``WorkspaceSetting`` so a deleted draft is never recreated.

On every run, a seeded social draft that is still untouched gets the brand's
connected Facebook, Instagram and X channels added and is submitted for review.
That is as far as automation goes: nothing is approved or scheduled here, and
in these workspaces only the approver, in the dashboard, can do either.
"""

import io
import zoneinfo
from datetime import datetime, time, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.approvals.actor import SYSTEM, acting_as
from apps.composer.models import PlatformPost, Post, PostMedia
from apps.settings_manager.models import WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.workspaces.brand_content import BLOG_DRAFTS, SOCIAL_DRAFTS
from apps.workspaces.management.commands.setup_brands import ensure_brand_workspaces, mask_email, resolve_approver

SEED_PREFIX = "seed."
#: Platforms the seeded drafts go to when the brand has them connected.
SEED_PLATFORMS = ("facebook", "instagram", "instagram_login", "x")
#: A seeded draft is "untouched" while every channel is in one of these.
UNTOUCHED = {"draft", "pending_review"}


def _marker(ws, key):
    return WorkspaceSetting.objects.filter(workspace=ws, key=f"{SEED_PREFIX}{key}").first()


def _set_marker(ws, key, value):
    WorkspaceSetting.objects.update_or_create(workspace=ws, key=f"{SEED_PREFIX}{key}", defaults={"value": value})


def proposed_time(ws, day, hhmm, *, base=None):
    tz = zoneinfo.ZoneInfo(ws.effective_timezone or "Asia/Kolkata")
    base = base or timezone.now().astimezone(tz).date()
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(base + timedelta(days=day), time(hour, minute), tzinfo=tz)


def fetch_image(url, name, *, timeout=20):
    """Download a brand image and return it as a JPEG upload, or None."""
    import httpx
    from PIL import Image

    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "SM-Manager-seed/1.0", "Accept": "image/jpeg,image/png;q=0.9,image/webp;q=0.8"},
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        img = img.convert("RGB")
        if img.width > 1600:
            img = img.resize((1600, round(img.height * 1600 / img.width)))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88)
        return SimpleUploadedFile(f"{name}.jpg", out.getvalue(), content_type="image/jpeg")
    except Exception:
        return None


def _attach_image(ws, approver, post, item, log):
    from apps.media_library.services import create_asset

    upload = fetch_image(item["image"], item["key"])
    if upload is None:
        log(f"  image not fetched for {item['key']} ({item['image']}); draft has no media yet")
        return None
    asset = create_asset(
        ws.organization,
        ws,
        upload,
        approver,
        alt_text=item.get("image_alt", ""),
        title=item.get("title", ""),
        tags=["seed", "brand-website"],
    )
    PostMedia.objects.create(post=post, media_asset=asset, position=0, alt_text=item.get("image_alt", ""))
    return asset


def seed_social(ws, approver, items, *, log):
    created, attached = 0, 0
    for item in items:
        marker = _marker(ws, item["key"])
        if marker is None:
            when = proposed_time(ws, item["day"], item["time"])
            notes = (
                "Test draft prepared from the brand's own website — nothing here is new information.\n"
                f"Sources: {', '.join(item['sources'])}\n"
                f"Proposed slot: {timezone.localtime(when, when.tzinfo):%a %d %b %Y, %H:%M} IST "
                "(seven-day calendar).\n"
                "Waiting for approval in the dashboard. It cannot be scheduled or published until approved."
            )
            post = Post.objects.create(
                workspace=ws,
                author=approver,
                title=item["title"],
                caption=item["caption"],
                internal_notes=notes,
                proposed_publish_at=when,
                tags=["seed", "seven-day-plan"],
            )
            _attach_image(ws, approver, post, item, log)
            _set_marker(ws, item["key"], {"post_id": str(post.id), "proposed_at": when.isoformat()})
            created += 1
            log(f"  created draft '{item['title']}' ({post.id}) proposed {when:%Y-%m-%d %H:%M %Z}")
        else:
            post = Post.objects.filter(pk=(marker.value or {}).get("post_id"), workspace=ws).first()
            if post is None:
                continue  # deleted by the owner — never recreate
            untouched = all(pp.status in UNTOUCHED for pp in post.platform_posts.all())
            if untouched and not post.media_attachments.exists():
                _attach_image(ws, approver, post, item, log)  # the download failed last time
        attached += _attach_channels(ws, approver, post, item, log)
    return created, attached


def _attach_channels(ws, approver, post, item, log):
    children = list(post.platform_posts.all())
    if any(pp.status not in UNTOUCHED for pp in children):
        return 0  # someone has acted on it — leave it alone
    have = {pp.social_account_id for pp in children}
    accounts = SocialAccount.objects.filter(workspace=ws, platform__in=SEED_PLATFORMS).exclude(
        connection_status=SocialAccount.ConnectionStatus.DISCONNECTED
    )
    added = []
    for account in accounts:
        if account.id in have:
            continue
        if account.platform in ("instagram", "instagram_login") and not post.media_attachments.exists():
            continue  # Instagram cannot publish without media
        added.append(
            PlatformPost.objects.create(
                post=post,
                social_account=account,
                status="draft",
                platform_specific_caption=item.get("x_caption") if account.platform == "x" else None,
            )
        )
    if not added:
        return 0
    from apps.approvals.services import submit_for_review

    with acting_as(None, SYSTEM):
        submit_for_review(post, approver, ws)
    names = ", ".join(f"{a.social_account.platform}:{a.social_account.account_name}" for a in added)
    log(f"  '{post.title}': added {names}; submitted for review")
    return len(added)


def seed_blogs(ws, approver, brand_key, *, log):
    item = BLOG_DRAFTS.get(brand_key)
    if not item or _marker(ws, item["key"]) is not None:
        return 0
    from apps.blog.models import BlogSite

    site = BlogSite.objects.filter(workspace=ws, is_enabled=True).order_by("created_at").first()
    if site is None:
        log("  no blog site for this workspace; blog draft skipped")
        return 0
    asset = None
    upload = fetch_image(item["image"], item["key"])
    if upload is not None:
        from apps.media_library.services import create_asset

        asset = create_asset(
            ws.organization,
            ws,
            upload,
            approver,
            alt_text=item["image_alt"],
            title=item["title"],
            tags=["seed", "blog"],
        )
    from apps.blog import services as blog

    with acting_as(None, SYSTEM):
        post = blog.create_post(
            workspace=ws,
            site=site,
            author=approver,
            title=item["title"],
            slug=item["slug"],
            excerpt=item["excerpt"],
            body=item["body"],
            featured_image=asset,
            featured_image_alt=item["image_alt"] if asset else "",
            seo_title=item["seo_title"],
            meta_description=item["meta_description"],
            category=item["category"],
            faq=item["faq"],
        )
        _set_marker(ws, item["key"], {"blog_post_id": str(post.pk)})
        blog.submit_for_review(post, approver)
    log(f"  created blog draft '{item['title']}' ({post.pk}) on {site.repo}; submitted for approval")
    return 1


class Command(BaseCommand):
    help = "Seed the brands' test drafts and seven-day plan (drafts only; nothing is approved or scheduled)."

    def add_arguments(self, parser):
        parser.add_argument("--approver-email", default=None)

    def handle(self, *args, approver_email=None, **options):
        approver = resolve_approver(approver_email)
        if approver is None:
            raise CommandError("No approver: pass --approver-email or set BRAND_APPROVER_EMAIL.")

        def log(message):
            self.stdout.write(f"seed_brand_content: {message}")

        log(f"approver {mask_email(approver.email)}")
        workspaces = ensure_brand_workspaces(approver, log=lambda m: None)
        for brand_key, ws in workspaces.items():
            log(f"{ws.name} ({ws.id})")
            created, attached = seed_social(ws, approver, SOCIAL_DRAFTS.get(brand_key, []), log=log)
            blogs = seed_blogs(ws, approver, brand_key, log=log)
            log(f"  {created} social drafts created, {attached} channels attached, {blogs} blog drafts created")
        self.stdout.write(self.style.SUCCESS("seed_brand_content: done"))
