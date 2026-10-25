"""The brand page's test hooks change nothing a person sees or a screen reader reads.

The two colour inputs carry a ``data-testid`` (``brand-primary-color``, ``brand-accent-color``), so
they are not rendered by ``blog/partials/field.html``. These tests pin that each one is still the
form's own widget, attribute for attribute (name, id, value, type, maxlength, class, required,
aria-invalid, aria-describedby), with only the ``data-testid`` added, on a fresh page and after an
invalid colour, and that every id its ``aria-describedby`` names is on the page. A change to the
form, the model's ``max_length`` or the field's help text reaches the inputs, and a template that
drifts from the widget fails here.
"""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.studio import design
from apps.studio.forms import BrandProfileForm
from apps.studio.models import BrandProfile

COLOURS = {"primary_color": "brand-primary-color", "accent_color": "brand-accent-color"}


class _Tags(HTMLParser):
    """Every start tag on the page, with its attributes in order (a repeated attribute is kept twice)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, list[tuple[str, str | None]]]] = []
        self.text_by_id: dict[str, str] = {}
        self._open: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))
        if tag not in ("input", "img", "br", "meta", "link"):
            self._open.append((tag, dict(attrs).get("id")))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, attrs))

    def handle_endtag(self, tag):
        while self._open:
            open_tag, _ = self._open.pop()
            if open_tag == tag:
                break

    def handle_data(self, data):
        for _tag, element_id in self._open:
            if element_id:
                self.text_by_id[element_id] = self.text_by_id.get(element_id, "") + data


def _parse(html: str) -> _Tags:
    parser = _Tags()
    parser.feed(html)
    return parser


def _by_testid(page: _Tags, testid: str) -> list[tuple[str, list[tuple[str, str | None]]]]:
    return [(tag, attrs) for tag, attrs in page.tags if dict(attrs).get("data-testid") == testid]


def _widget_attrs(form: BrandProfileForm, name: str) -> list[tuple[str, str | None]]:
    """The attributes Django's own widget renders for the field (what ``{{ field }}`` prints)."""
    rendered = _parse(str(form[name]))
    assert [tag for tag, _attrs in rendered.tags] == ["input"]
    return rendered.tags[0][1]


def _url(world, name="brand", **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": world.workspace.id, **kwargs})


def _valid_data(profile: BrandProfile) -> dict[str, str]:
    form = BrandProfileForm(instance=profile)
    return {name: "" if form[name].value() is None else str(form[name].value()) for name in form.fields}


def _assert_is_the_widget(page: _Tags, form: BrandProfileForm, name: str, testid: str) -> dict[str, str | None]:
    found = _by_testid(page, testid)
    assert len(found) == 1, f"one element carries data-testid={testid!r}"
    tag, attrs = found[0]
    assert tag == "input"
    assert len(attrs) == len(dict(attrs)), f"no attribute is written twice on {testid}: {attrs}"
    widget = _widget_attrs(form, name)
    assert len(widget) == len(dict(widget))
    rendered = dict(attrs)
    # Attribute for attribute (their order means nothing to a browser), with only the data-testid added.
    assert {key: value for key, value in rendered.items() if key != "data-testid"} == dict(widget)
    # The label names the input, and every id aria-describedby names is on the page.
    labels = [dict(label_attrs) for label_tag, label_attrs in page.tags if label_tag == "label"]
    assert any(label.get("for") == rendered["id"] for label in labels)
    for described_by in (rendered.get("aria-describedby") or "").split():
        assert described_by in page.text_by_id, f"{testid}: aria-describedby names {described_by!r}, not on the page"
    return rendered


@pytest.mark.django_db
def test_the_colour_inputs_are_the_forms_own_widgets_with_a_testid(client, world):
    client.force_login(world.owner)

    response = client.get(_url(world))

    assert response.status_code == 200
    page = _parse(response.content.decode())
    form = BrandProfileForm(instance=BrandProfile.objects.get(workspace=world.workspace))
    for name, testid in COLOURS.items():
        rendered = _assert_is_the_widget(page, form, name, testid)
        assert rendered["type"] == "color" and "aria-invalid" not in rendered


@pytest.mark.django_db
def test_an_invalid_colour_is_announced_by_the_error_its_input_names(client, world):
    client.force_login(world.owner)
    client.get(_url(world))
    profile = BrandProfile.objects.get(workspace=world.workspace)
    data = {**_valid_data(profile), "primary_color": "teal"}

    response = client.post(_url(world), data)

    assert response.status_code == 200
    form = response.context["form"]
    assert list(form.errors) == ["primary_color"]
    page = _parse(response.content.decode())
    expected = BrandProfileForm(data, instance=BrandProfile.objects.get(workspace=world.workspace))
    assert not expected.is_valid()
    primary = _assert_is_the_widget(page, expected, "primary_color", COLOURS["primary_color"])
    accent = _assert_is_the_widget(page, expected, "accent_color", COLOURS["accent_color"])
    assert primary["value"] == "teal" and primary["aria-invalid"] == "true"
    error_id = primary["aria-describedby"]
    assert error_id
    error = next(dict(attrs) for _tag, attrs in page.tags if dict(attrs).get("id") == error_id)
    assert error.get("role") == "alert"
    assert str(form.errors["primary_color"][0]) in page.text_by_id[error_id]
    assert "aria-invalid" not in accent and "aria-describedby" not in accent


@pytest.mark.django_db
def test_a_colours_help_text_is_shown_and_named_by_its_input(client, world, monkeypatch):
    monkeypatch.setattr(BrandProfileForm.base_fields["accent_color"], "help_text", "Used for buttons and highlights.")
    client.force_login(world.owner)

    response = client.get(_url(world))

    page = _parse(response.content.decode())
    form = BrandProfileForm(instance=BrandProfile.objects.get(workspace=world.workspace))
    accent = _assert_is_the_widget(page, form, "accent_color", COLOURS["accent_color"])
    assert accent["aria-describedby"] == f"{accent['id']}_helptext"
    assert page.text_by_id[f"{accent['id']}_helptext"].strip() == "Used for buttons and highlights."


@pytest.mark.django_db
def test_each_sample_image_has_its_own_testid(client, world):
    client.force_login(world.owner)

    page = _parse(client.get(_url(world)).content.decode())

    for template in design.TEMPLATES:
        found = _by_testid(page, f"brand-sample-image-{template}")
        assert len(found) == 1, template
        tag, attrs = found[0]
        assert tag == "img"
        assert dict(attrs)["src"].startswith(_url(world, "brand_sample", template=template))
