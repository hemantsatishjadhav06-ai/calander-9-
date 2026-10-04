from django import forms
from django.core.exceptions import ValidationError

from apps.media_library.models import MediaAsset

from .models import BlogPost, BlogSite

RECENT_IMAGE_LIMIT = 30

_INPUT = (
    "w-full px-3 py-2 text-sm rounded-lg border border-stone-300 bg-white text-stone-900 "
    "focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-orange-500"
)


def parse_faq(text: str) -> list[dict]:
    """Parse ``Q: …`` / ``A: …`` blocks into ``[{"q": …, "a": …}]``.

    A question or answer may continue on the following lines; a new ``Q:``
    starts the next entry.
    """
    entries: list[dict] = []
    current: dict | None = None
    field = None
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        upper = line[:2].upper()
        if upper == "Q:":
            if current is not None:
                entries.append(current)
            current = {"q": line[2:].strip(), "a": ""}
            field = "q"
        elif upper == "A:":
            if current is None:
                raise ValidationError(f'Line {number}: an answer needs a question above it ("Q: …").')
            if current["a"]:
                raise ValidationError(f"Line {number}: this question already has an answer.")
            current["a"] = line[2:].strip()
            field = "a"
        else:
            if current is None:
                raise ValidationError(f'Line {number}: start each entry with "Q:".')
            current[field] = f"{current[field]} {line}".strip()
    if current is not None:
        entries.append(current)
    for index, entry in enumerate(entries, start=1):
        if not entry["q"] or not entry["a"]:
            raise ValidationError(f"FAQ entry {index} needs both a question (Q:) and an answer (A:).")
    return entries


def format_faq(faq) -> str:
    return "\n\n".join(f"Q: {item['q']}\nA: {item['a']}" for item in (faq or []))


class BlogPostForm(forms.ModelForm):
    faq_text = forms.CharField(
        label="FAQ (optional)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6, "class": _INPUT + " font-mono"}),
        help_text='One entry per question: a line starting "Q:" then a line starting "A:". '
        "Shown at the end of the post and marked up as FAQ for search engines.",
    )

    class Meta:
        model = BlogPost
        fields = [
            "site",
            "title",
            "slug",
            "excerpt",
            "body",
            "featured_image",
            "featured_image_alt",
            "cover_style",
            "seo_title",
            "meta_description",
            "category",
        ]
        labels = {
            "site": "Website",
            "slug": "Address (slug)",
            "excerpt": "Excerpt",
            "body": "Body (Markdown)",
            "featured_image": "Featured image",
            "featured_image_alt": "Featured image description (alt text)",
            "cover_style": "Cover",
            "seo_title": "SEO title",
            "meta_description": "Meta description",
        }
        help_texts = {
            "slug": "Lowercase letters, numbers and hyphens. It becomes the page address and can't change once published.",
            "excerpt": "One or two sentences for the blog index card and social drafts.",
            "body": "Markdown: ## headings, **bold**, lists, links and tables. Scripts and embeds are removed.",
            "seo_title": "Shown in search results and browser tabs. Defaults to the title.",
            "meta_description": "The search-result snippet. Defaults to the excerpt.",
            "category": "Shown above the title and on the card, e.g. Buyer Guide.",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": _INPUT}),
            "slug": forms.TextInput(
                attrs={"class": _INPUT + " font-mono", "autocapitalize": "none", "spellcheck": "false"}
            ),
            "excerpt": forms.Textarea(attrs={"rows": 3, "class": _INPUT, "maxlength": 400}),
            "body": forms.Textarea(attrs={"rows": 22, "class": _INPUT + " font-mono"}),
            "featured_image_alt": forms.TextInput(attrs={"class": _INPUT}),
            "cover_style": forms.RadioSelect(),
            "seo_title": forms.TextInput(attrs={"class": _INPUT}),
            "meta_description": forms.Textarea(attrs={"rows": 3, "class": _INPUT}),
            "category": forms.TextInput(attrs={"class": _INPUT}),
            "site": forms.Select(attrs={"class": _INPUT}),
        }

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        sites = BlogSite.objects.filter(workspace=workspace, is_enabled=True)
        if self.instance.site_id:
            sites = BlogSite.objects.filter(workspace=workspace).filter(
                pk__in=[self.instance.site_id, *sites.values_list("pk", flat=True)]
            )
        self.fields["site"].queryset = sites.order_by("name")
        self.fields["site"].empty_label = None
        self.fields["title"].widget.attrs["autofocus"] = not self.instance.pk

        images = MediaAsset.objects.for_workspace_with_shared(workspace.id, workspace.organization_id).filter(
            media_type=MediaAsset.MediaType.IMAGE
        )
        recent_ids = list(images.order_by("-created_at").values_list("id", flat=True)[:RECENT_IMAGE_LIMIT])
        if self.instance.featured_image_id:
            recent_ids.append(self.instance.featured_image_id)
        self.fields["featured_image"].queryset = MediaAsset.objects.filter(pk__in=recent_ids).order_by("-created_at")
        self.fields["featured_image"].required = False
        self.fields["featured_image"].widget = forms.RadioSelect()
        # A form posted without a cover choice (older clients, scripts) keeps
        # the default rather than failing validation.
        self.fields["cover_style"].required = False

        if not self.is_bound and self.instance.pk:
            self.fields["faq_text"].initial = format_faq(self.instance.faq)

        # Alpine bindings for the slug suggestion and the character counters.
        self.fields["title"].widget.attrs.update({"x-model": "title", "x-on:input": "onTitle()"})
        self.fields["slug"].widget.attrs.update({"x-model": "slug", "x-on:input": "slugTouched = true"})
        self.fields["site"].widget.attrs.update({"x-model": "site"})
        self.fields["seo_title"].widget.attrs.update({"x-model": "seo"})
        self.fields["meta_description"].widget.attrs.update({"x-model": "meta"})
        if self.slug_locked:
            self.fields["slug"].disabled = True
            self.fields["site"].disabled = True

    @property
    def slug_locked(self) -> bool:
        """A post's address and website are fixed once it has been committed to the site."""
        return bool(self.instance.pk and self.instance.has_been_committed)

    def alpine_state(self) -> dict:
        def value(name):
            bound = self[name].value()
            return "" if bound is None else str(bound)

        sites = self.fields["site"].queryset  # type: ignore[attr-defined]
        return {
            "title": value("title"),
            "slug": value("slug"),
            "slugTouched": bool(self.instance.pk) or bool(value("slug")),
            "slugLocked": self.slug_locked,
            "seo": value("seo_title"),
            "meta": value("meta_description"),
            "site": value("site"),
            "siteUrls": {str(site.pk): site.live_url_for("__slug__") for site in sites},
        }

    @property
    def image_choices(self):
        return list(self.fields["featured_image"].queryset)

    def clean_slug(self):
        return (self.cleaned_data.get("slug") or "").strip().lower()

    def clean_cover_style(self):
        return self.cleaned_data.get("cover_style") or BlogPost.CoverStyle.DESIGNED

    def clean_faq_text(self):
        return parse_faq(self.cleaned_data.get("faq_text", ""))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("featured_image") and not (cleaned.get("featured_image_alt") or "").strip():
            self.add_error("featured_image_alt", "Describe the image for people who can't see it.")
        site, slug = cleaned.get("site"), cleaned.get("slug")
        if site and slug and BlogPost.objects.filter(site=site, slug=slug).exclude(pk=self.instance.pk).exists():
            self.add_error("slug", "Another post on this website already uses this address.")
        return cleaned

    def _post_clean(self):
        # The model's clean() validates the FAQ list, so put it on the instance first.
        if "faq_text" in self.cleaned_data:
            self.instance.faq = self.cleaned_data["faq_text"]
        super()._post_clean()

    def content_changes(self) -> dict:
        data = {name: self.cleaned_data[name] for name in self.Meta.fields}
        data["faq"] = self.cleaned_data.get("faq_text", [])
        return data
