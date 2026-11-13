"""Tests for the opt-in ``normalize_json`` parse option.

When ``normalize_json`` is enabled, JSON Feed 1/1.1 data is normalized into
the same output shape that the XML (RSS/Atom) parsers produce. These tests
are fully offline: every feed is parsed from an in-memory stream.
"""

from __future__ import annotations

import copy
import io
import json

import feedparser
from feedparser.util import FeedParserDict

JSON_HEADERS = {"content-type": "application/feed+json"}
BASE_HEADERS = {
    "content-type": "application/feed+json",
    "content-location": "https://example.org/feed.json",
}


def parse_json(payload: dict, *, normalize: bool = False, headers=None, **kwargs):
    data = json.dumps(payload).encode("utf-8")
    return feedparser.parse(
        io.BytesIO(data),
        response_headers=headers or JSON_HEADERS,
        normalize_json=normalize,
        **kwargs,
    )


def make_feed(items: list[dict], **feed_fields) -> dict:
    feed = {"version": "https://jsonfeed.org/version/1.1", "title": "Feed"}
    feed.update(feed_fields)
    feed["items"] = items
    return feed


# ---------------------------------------------------------------------------
# The historical JSON output must remain byte-for-byte identical in shape
# when normalize_json is not enabled (it defaults to False).
# ---------------------------------------------------------------------------


def test_normalize_json_defaults_to_off():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_text": "plain",
                "content_html": "<p>html</p>",
                "tags": ["a"],
                "author": {"name": "A"},
                "attachments": [{"url": "https://e.test/a", "mime_type": "video/mp4"}],
            }
        ]
    )
    default = parse_json(payload)
    explicit = parse_json(payload, normalize=False)
    assert default == explicit

    entry = default.entries[0]
    # Legacy content is a single dict with non-MIME type values.
    assert entry.content == {"value": "plain", "type": "text"}
    # Legacy tags are exposed through the ``category`` list alias.
    assert "tags" not in dict(entry)
    assert dict.__getitem__(entry, "category") == ["a"]
    # Legacy attachments populate ``enclosures`` directly, with no ``links``.
    assert "links" not in entry
    assert dict.__getitem__(entry, "enclosures") == [
        {"href": "https://e.test/a", "type": "video/mp4"}
    ]
    # Legacy singular author fields only.
    assert "authors" not in entry
    assert entry.author == "A"
    assert entry.author_detail == {"name": "A"}


def test_legacy_content_html_is_sanitized_regardless_of_sanitize_flag():
    payload = make_feed(
        [{"id": "1", "content_html": "<p>ok</p><script>alert(1)</script>"}]
    )
    for kwargs in ({}, {"sanitize_html": False}, {"sanitize_html": True}):
        result = parse_json(payload, **kwargs)
        assert result.entries[0].content == {
            "value": "<p>ok</p>",
            "type": "html",
        }


def test_legacy_date_updated_key_handling_unchanged():
    # The historical code keys off ``date_updated`` but reads
    # ``date_modified``; that quirk must be preserved when the option is off.
    # An entry carrying ``date_updated`` without ``date_modified`` therefore
    # raises a KeyError, which the public API records as a bozo exception.
    payload = make_feed([{"id": "1", "date_updated": True}])
    result = parse_json(payload)
    assert result.bozo == 1
    assert isinstance(result.bozo_exception, KeyError)

    # The normalized parser keys off the correct ``date_modified`` field
    # and is unaffected by a stray ``date_updated`` key.
    fixed = parse_json(
        make_feed(
            [
                {
                    "id": "1",
                    "date_updated": True,
                    "date_modified": "2020-01-02T03:04:05Z",
                }
            ]
        ),
        normalize=True,
    )
    assert fixed.bozo == 0
    assert fixed.entries[0].updated == "2020-01-02T03:04:05Z"


# ---------------------------------------------------------------------------
# content: always a list, standard MIME types, dual bodies retained in order.
# ---------------------------------------------------------------------------


def test_content_is_a_list_with_standard_mime_types():
    payload = make_feed(
        [
            {"id": "text-only", "content_text": "plain"},
            {"id": "html-only", "content_html": "<p>html</p>"},
            {
                "id": "both",
                "content_text": "plain",
                "content_html": "<p>html</p>",
            },
        ]
    )
    result = parse_json(payload, normalize=True, headers=BASE_HEADERS)
    entries = {entry.id: entry for entry in result.entries}

    text_entry = entries["text-only"]
    assert len(text_entry.content) == 1
    assert text_entry.content[0].type == "text/plain"
    assert text_entry.content[0].value == "plain"
    assert text_entry.content[0].base == "https://example.org/feed.json"

    html_entry = entries["html-only"]
    assert [c.type for c in html_entry.content] == ["text/html"]

    both = entries["both"]
    assert [c.type for c in both.content] == ["text/plain", "text/html"]
    assert [c.value for c in both.content] == ["plain", "<p>html</p>"]
    # Every content dict carries the XML-style metadata keys.
    for content in both.content:
        assert set(content) == {"value", "type", "base", "language"}


def test_plain_text_and_id_are_not_rewritten():
    payload = make_feed(
        [
            {
                "id": "../relative-id",
                "content_text": "visit /relative and <tag>",
                "content_html": "<p>x</p>",
            }
        ]
    )
    result = parse_json(payload, normalize=True, headers=BASE_HEADERS)
    entry = result.entries[0]
    assert entry.id == "../relative-id"
    assert entry.content[0].value == "visit /relative and <tag>"


def test_html_honors_sanitize_and_resolve_relative_uri_switches():
    html = '<p>hi <a href="/rel">x</a></p><script>alert(1)</script>'
    payload = make_feed([{"id": "1", "content_html": html}])

    # Defaults: sanitization on, relative-URI resolution on.
    result = parse_json(payload, normalize=True, headers=BASE_HEADERS)
    assert result.entries[0].content[0].value == (
        '<p>hi <a href="https://example.org/rel">x</a></p>'
    )

    result = parse_json(
        payload,
        normalize=True,
        headers=BASE_HEADERS,
        sanitize_html=False,
        resolve_relative_uris=False,
    )
    assert result.entries[0].content[0].value == html

    result = parse_json(
        payload,
        normalize=True,
        headers=BASE_HEADERS,
        sanitize_html=True,
        resolve_relative_uris=False,
    )
    assert result.entries[0].content[0].value == '<p>hi <a href="/rel">x</a></p>'

    result = parse_json(
        payload,
        normalize=True,
        headers=BASE_HEADERS,
        sanitize_html=False,
        resolve_relative_uris=True,
    )
    assert result.entries[0].content[0].value == (
        '<p>hi <a href="https://example.org/rel">x</a></p><script>alert(1)</script>'
    )


def test_relative_uri_resolution_requires_a_valid_base():
    payload = make_feed([{"id": "1", "content_html": '<a href="/rel">x</a>'}])
    # No Content-Location and no href: the base URI is empty and the
    # relative URI must be left untouched rather than mangled.
    result = parse_json(payload, normalize=True)
    assert result.entries[0].content[0].value == '<a href="/rel">x</a>'
    assert result.entries[0].content[0].base == ""


# ---------------------------------------------------------------------------
# tags and the category alias.
# ---------------------------------------------------------------------------


def test_tags_use_xml_shape():
    payload = make_feed([{"id": "1", "tags": ["one", "two", ""]}])
    result = parse_json(payload, normalize=True)
    assert result.entries[0].tags == [
        {"term": "one", "scheme": None, "label": None},
        {"term": "two", "scheme": None, "label": None},
    ]
    # The FeedParserDict ``category`` alias keeps working.
    assert result.entries[0].category == "one"
    assert "category" in result.entries[0]


def test_empty_tags_does_not_break_category_alias():
    payload = make_feed([{"id": "1", "tags": []}])
    result = parse_json(payload, normalize=True)
    assert result.entries[0].tags == []
    assert "category" not in result.entries[0]


# ---------------------------------------------------------------------------
# attachments -> links with rel="enclosure"; enclosures alias stays in sync.
# ---------------------------------------------------------------------------


def test_attachments_become_enclosure_links():
    payload = make_feed(
        [
            {
                "id": "1",
                "url": "https://example.org/p1",
                "attachments": [
                    {
                        "url": "https://example.org/a.mp4",
                        "mime_type": "video/mp4",
                        "size_in_bytes": 123,
                    },
                    {"url": "https://example.org/b.png", "mime_type": "image/png"},
                ],
            }
        ]
    )
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.links == [
        {"rel": "alternate", "type": "text/html", "href": "https://example.org/p1"},
        {
            "rel": "enclosure",
            "href": "https://example.org/a.mp4",
            "type": "video/mp4",
            "length": "123",
        },
        {
            "rel": "enclosure",
            "href": "https://example.org/b.png",
            "type": "image/png",
        },
    ]
    # The dynamic ``enclosures`` alias strips ``rel`` and matches the XML
    # enclosure shape (length is a string, as in XML feeds). The alias is
    # computed from ``links`` on access rather than stored separately.
    assert "enclosures" not in dict(entry)
    assert entry.enclosures == [
        {"href": "https://example.org/a.mp4", "type": "video/mp4", "length": "123"},
        {"href": "https://example.org/b.png", "type": "image/png"},
    ]


# ---------------------------------------------------------------------------
# authors: list-first, entry inheritance, explicit empty lists, deep copies.
# ---------------------------------------------------------------------------


def test_json1_single_author_becomes_authors_list():
    payload = make_feed(
        [{"id": "1", "author": {"name": "A", "url": "https://a.test/"}}]
    )
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.authors == [{"name": "A", "href": "https://a.test/"}]
    assert entry.author == "A"
    assert entry.author_detail == {"name": "A", "href": "https://a.test/"}


def test_mailto_author_url_becomes_email():
    payload = make_feed(
        [{"id": "1", "authors": [{"name": "A", "url": "mailto:a@example.org"}]}]
    )
    result = parse_json(payload, normalize=True)
    assert result.entries[0].authors == [{"name": "A", "email": "a@example.org"}]
    assert result.entries[0].author_detail.email == "a@example.org"


def test_multiple_authors_sync_singular_alias_to_last():
    payload = make_feed([{"id": "1", "authors": [{"name": "First"}, {"name": "Last"}]}])
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert [a.name for a in entry.authors] == ["First", "Last"]
    assert entry.author == "Last"
    assert entry.author_detail == {"name": "Last"}


def test_authors_list_takes_precedence_over_legacy_author():
    # When both the 1.1 ``authors`` list and the legacy 1.0 singular
    # ``author`` are present, the list wins and the singular value is ignored.
    payload = make_feed(
        [
            {
                "id": "1",
                "authors": [{"name": "From List"}],
                "author": {"name": "Legacy Singular"},
            }
        ],
        authors=[{"name": "Feed From List"}],
        author={"name": "Feed Legacy"},
    )
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.authors == [{"name": "From List"}]
    assert entry.author == "From List"
    assert result.feed.authors == [{"name": "Feed From List"}]
    assert result.feed.author == "Feed From List"


def test_entry_without_author_inherits_feed_authors():
    payload = make_feed(
        [
            {"id": "with", "authors": [{"name": "Own"}]},
            {"id": "inherited"},
        ],
        authors=[{"name": "Feed Author"}],
    )
    result = parse_json(payload, normalize=True)
    entries = {entry.id: entry for entry in result.entries}

    assert entries["with"].authors == [{"name": "Own"}]
    assert entries["with"].author == "Own"

    inherited = entries["inherited"]
    assert inherited.authors == [{"name": "Feed Author"}]
    assert inherited.author == "Feed Author"
    assert inherited.author_detail == {"name": "Feed Author"}
    # The feed itself keeps its own authors.
    assert result.feed.authors == [{"name": "Feed Author"}]
    assert result.feed.author == "Feed Author"


def test_explicit_empty_authors_does_not_inherit():
    payload = make_feed(
        [{"id": "1", "authors": []}],
        authors=[{"name": "Feed Author"}],
    )
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.authors == []
    assert "author" not in entry
    assert "author_detail" not in entry


def test_inherited_authors_are_deep_copied():
    payload = make_feed(
        [{"id": "a"}, {"id": "b"}],
        authors=[{"name": "Feed Author", "url": "https://f.test/"}],
    )
    result = parse_json(payload, normalize=True)
    feed_authors = result.feed.authors
    first = result.entries[0].authors
    second = result.entries[1].authors

    assert first == feed_authors and second == feed_authors
    assert first is not feed_authors
    assert second is not feed_authors
    assert first is not second
    assert first[0] is not feed_authors[0]

    # Mutating one copy must not leak into any other object.
    first[0]["name"] = "mutated"
    first.append({"name": "extra"})
    assert feed_authors == [{"name": "Feed Author", "href": "https://f.test/"}]
    assert second == [{"name": "Feed Author", "href": "https://f.test/"}]


def test_feed_without_authors_leaves_entries_without_them():
    payload = make_feed([{"id": "1"}])
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert "authors" not in entry
    assert "author" not in entry
    assert "authors" not in result.feed


# ---------------------------------------------------------------------------
# date_modified -> updated / updated_parsed (UTC).
# ---------------------------------------------------------------------------


def test_date_modified_generates_updated_and_utc_parsed_value():
    payload = make_feed([{"id": "1", "date_modified": "2020-01-02T03:04:05+02:00"}])
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.updated == "2020-01-02T03:04:05+02:00"
    # 03:04:05 at +02:00 is 01:04:05 UTC.
    assert entry.updated_parsed == (2020, 1, 2, 1, 4, 5, 3, 2, 0)
    assert entry.updated_parsed.tm_isdst == 0


def test_date_modified_uses_correct_json_feed_field():
    # JSON Feed 1/1.1 calls the field ``date_modified``; a stray
    # ``date_updated`` key must not crash normalized parsing.
    payload = make_feed(
        [
            {
                "id": "1",
                "date_updated": True,
                "date_modified": "2020-01-02T03:04:05Z",
            }
        ]
    )
    result = parse_json(payload, normalize=True)
    assert result.entries[0].updated == "2020-01-02T03:04:05Z"
    assert result.entries[0].updated_parsed[:6] == (2020, 1, 2, 3, 4, 5)


def test_published_and_updated_coexist():
    payload = make_feed(
        [
            {
                "id": "1",
                "date_published": "2020-01-01T00:00:00Z",
                "date_modified": "2020-01-02T00:00:00Z",
            }
        ]
    )
    result = parse_json(payload, normalize=True)
    entry = result.entries[0]
    assert entry.published == "2020-01-01T00:00:00Z"
    assert entry.updated == "2020-01-02T00:00:00Z"
    assert entry.published_parsed[:3] == (2020, 1, 1)
    assert entry.updated_parsed[:3] == (2020, 1, 2)


# ---------------------------------------------------------------------------
# Feed-level normalization.
# ---------------------------------------------------------------------------


def test_feed_links_include_alternate_and_self():
    payload = make_feed(
        [],
        home_page_url="https://example.org/",
        feed_url="https://example.org/feed.json",
    )
    result = parse_json(payload, normalize=True)
    assert result.feed.links == [
        {"rel": "alternate", "type": "text/html", "href": "https://example.org/"},
        {
            "rel": "self",
            "type": "application/feed+json",
            "href": "https://example.org/feed.json",
        },
    ]
    # The singular ``link`` field keeps being populated as before.
    assert result.feed.link == "https://example.org/"


def test_json1_feed_author_is_supported():
    payload = make_feed([], author={"name": "Old School"})
    result = parse_json(payload, normalize=True)
    assert result.feed.authors == [{"name": "Old School"}]
    assert result.feed.author == "Old School"
    assert result.feed.author_detail == {"name": "Old School"}


def test_json_feed_1_singular_author_normalizes_the_same_as_1_1():
    # JSON Feed 1 only has a singular ``author`` object (no ``authors``
    # list). It must normalize into the exact same shape as a 1.1 feed.
    payload = {
        "version": "https://jsonfeed.org/version/1",
        "title": "v1 feed",
        "author": {"name": "Feed Author"},
        "items": [
            {
                "id": "1",
                "author": {"name": "Entry Author"},
                "content_text": "plain",
                "content_html": "<p>html</p>",
                "tags": ["t"],
                "attachments": [{"url": "https://e.test/a", "mime_type": "audio/mpeg"}],
            }
        ],
    }
    result = parse_json(payload, normalize=True)
    assert result.version == "json1"
    entry = result.entries[0]
    assert [c.type for c in entry.content] == ["text/plain", "text/html"]
    assert entry.authors == [{"name": "Entry Author"}]
    assert entry.author == "Entry Author"
    assert entry.tags == [{"term": "t", "scheme": None, "label": None}]
    assert entry.enclosures == [{"href": "https://e.test/a", "type": "audio/mpeg"}]
    assert result.feed.authors == [{"name": "Feed Author"}]


# ---------------------------------------------------------------------------
# Cross-format regression: normalized JSON must match the XML shapes.
# ---------------------------------------------------------------------------


ATOM_FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Feed</title>
  <link rel="alternate" type="text/html" href="https://example.org/"/>
  <link rel="self" type="application/atom+xml"
        href="https://example.org/feed.atom"/>
  <author><name>Feed Author</name></author>
  <entry>
    <title>post</title>
    <id>tag:example,2020:1</id>
    <link rel="alternate" type="text/html"
          href="https://example.org/p1"/>
    <link rel="enclosure" type="video/mp4" length="123"
          href="https://example.org/a.mp4"/>
    <category term="one"/>
    <category term="two"/>
    <content type="text/plain">plain body</content>
    <content type="text/html">&lt;p&gt;html body&lt;/p&gt;</content>
    <published>2020-01-01T00:00:00Z</published>
    <updated>2020-01-02T03:04:05+02:00</updated>
    <author><name>Entry Author</name><email>e@example.org</email></author>
  </entry>
</feed>"""

JSON_FEED = make_feed(
    [
        {
            "id": "tag:example,2020:1",
            "title": "post",
            "url": "https://example.org/p1",
            "content_text": "plain body",
            "content_html": "<p>html body</p>",
            "date_published": "2020-01-01T00:00:00Z",
            "date_modified": "2020-01-02T03:04:05+02:00",
            "tags": ["one", "two"],
            "authors": [{"name": "Entry Author", "url": "mailto:e@example.org"}],
            "attachments": [
                {
                    "url": "https://example.org/a.mp4",
                    "mime_type": "video/mp4",
                    "size_in_bytes": 123,
                }
            ],
        }
    ],
    home_page_url="https://example.org/",
    feed_url="https://example.org/feed.atom",
    authors=[{"name": "Feed Author"}],
)


def test_normalized_json_matches_atom_shape():
    atom = feedparser.parse(io.BytesIO(ATOM_FEED))
    normalized = parse_json(JSON_FEED, normalize=True)

    atom_entry = atom.entries[0]
    json_entry = normalized.entries[0]

    # Content list with identical MIME types and values.
    assert [c.type for c in json_entry.content] == [c.type for c in atom_entry.content]
    assert [c.value for c in json_entry.content] == [
        c.value for c in atom_entry.content
    ]
    # Tags.
    assert json_entry.tags == atom_entry.tags
    # Links/enclosures (ignoring key ordering).
    assert json_entry.links == atom_entry.links
    assert json_entry.enclosures == atom_entry.enclosures
    # Authors.
    assert json_entry.authors == atom_entry.authors
    assert json_entry.author_detail == atom_entry.author_detail
    # Dates, including the UTC-normalized struct time.
    assert json_entry.published_parsed == atom_entry.published_parsed
    assert json_entry.updated_parsed == atom_entry.updated_parsed
    # Feed-level authors and links.
    assert normalized.feed.authors == atom.feed.authors
    assert normalized.feed.links[0] == atom.feed.links[0]


def test_normalized_json_values_are_feedparser_dicts():
    result = parse_json(
        make_feed(
            [
                {
                    "id": "1",
                    "content_text": "plain",
                    "tags": ["t"],
                    "authors": [{"name": "A"}],
                }
            ]
        ),
        normalize=True,
    )
    entry = result.entries[0]
    assert isinstance(entry, FeedParserDict)
    assert isinstance(entry.tags[0], FeedParserDict)
    assert isinstance(entry.authors[0], FeedParserDict)
    assert isinstance(entry.content[0], FeedParserDict)


# ---------------------------------------------------------------------------
# Consecutive parses with different configurations must not influence each
# other (parser state is per-parse, and the module constants are untouched).
# ---------------------------------------------------------------------------


def test_consecutive_parses_with_different_configurations():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_html": '<p><a href="/rel">x</a></p><script>x</script>',
            }
        ]
    )

    first = parse_json(payload, normalize=True, headers=BASE_HEADERS)
    second = parse_json(payload)  # legacy mode, default flags
    third = parse_json(
        payload,
        normalize=True,
        headers=BASE_HEADERS,
        sanitize_html=False,
        resolve_relative_uris=False,
    )
    fourth = parse_json(payload, normalize=True, headers=BASE_HEADERS)

    assert first.entries[0].content[0].value == (
        '<p><a href="https://example.org/rel">x</a></p>'
    )
    # Legacy output is unaffected by earlier normalized parses.
    assert second.entries[0].content == {
        "value": '<p><a href="/rel">x</a></p>',
        "type": "html",
    }
    # Explicitly disabled switches are honored on this parse only.
    assert third.entries[0].content[0].value == (
        '<p><a href="/rel">x</a></p><script>x</script>'
    )
    # A later parse picks up the defaults again.
    assert fourth.entries[0].content[0].value == (
        '<p><a href="https://example.org/rel">x</a></p>'
    )


def test_normalize_json_works_through_xml_fallback_path(monkeypatch):
    # When the XML parsers are unavailable, JSON-looking data is routed
    # through the fallback JSON parser path; the option must survive that.
    import feedparser.api

    monkeypatch.setattr(feedparser.api, "_XML_AVAILABLE", False)
    payload = make_feed([{"id": "1", "content_text": "plain"}])
    data = json.dumps(payload).encode("utf-8")
    result = feedparser.parse(
        io.BytesIO(data),
        response_headers=JSON_HEADERS,
        normalize_json=True,
    )
    assert result.entries[0].content[0].type == "text/plain"
    assert isinstance(result.entries[0].content, list)


def test_deepcopy_of_normalized_result_is_independent():
    payload = make_feed([{"id": "1"}], authors=[{"name": "Feed Author"}])
    result = parse_json(payload, normalize=True)
    snapshot = copy.deepcopy(result)
    result.entries[0].authors[0]["name"] = "changed"
    assert snapshot.entries[0].authors[0]["name"] == "Feed Author"
