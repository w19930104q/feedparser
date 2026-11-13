"""Offline regression tests for the opt-in normalized JSON feed output.

The normalized mode is enabled with ``parse(normalize_json_feeds=True)``
(or by setting ``feedparser.NORMALIZE_JSON_FEEDS`` to a true value).
It is disabled by default, so the historical JSON feed output is preserved.
"""

from __future__ import annotations

import copy
import io
import json

import pytest
import responses

import feedparser

JSON_11 = "https://jsonfeed.org/version/1.1"
JSON_10 = "https://jsonfeed.org/version/1"


def parse_json(payload, **kwargs):
    kwargs.setdefault("response_headers", {"content-type": "application/feed+json"})
    return feedparser.parse(io.BytesIO(json.dumps(payload).encode("utf-8")), **kwargs)


def make_feed(items, **feed_fields):
    feed = {"version": JSON_11, "title": "Example", "items": items}
    feed.update(feed_fields)
    return feed


# ---------------------------------------------------------------------
# Default-off: the legacy JSON feed output must remain unchanged.
# ---------------------------------------------------------------------


def test_normalization_is_disabled_by_default():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_text": "plain",
                "content_html": "<p>html</p>",
                "tags": ["a", "b"],
                "attachments": [
                    {"url": "https://example.org/a.mp3", "mime_type": "audio/mpeg"}
                ],
            }
        ]
    )
    result = parse_json(payload)

    assert feedparser.NORMALIZE_JSON_FEEDS == 0
    # Legacy ``content`` is a single dictionary, not a list.
    content = result.entries[0].content
    assert isinstance(content, feedparser.FeedParserDict)
    assert content == {"value": "plain", "type": "text"}
    # Legacy tags are stored as raw ``category`` strings. The pre-existing
    # FeedParserDict ``category`` accessor is tags-based and does not read
    # this raw key, so the stored value is inspected through the base dict.
    assert dict.__getitem__(result.entries[0], "category") == ["a", "b"]
    with pytest.raises(KeyError):
        result.entries[0]["category"]
    # Legacy attachments are a plain list of enclosure dictionaries. Like
    # ``category`` above, the virtual ``enclosures`` accessor is links-based,
    # so the legacy raw key is inspected via the base dict.
    assert dict.__getitem__(result.entries[0], "enclosures") == [
        {"href": "https://example.org/a.mp3", "type": "audio/mpeg"}
    ]
    assert "links" not in result.entries[0]
    assert "tags" not in result.entries[0]


def test_module_level_flag_enables_normalization(monkeypatch):
    monkeypatch.setattr(feedparser, "NORMALIZE_JSON_FEEDS", 1)
    payload = make_feed([{"id": "1", "content_text": "plain"}])
    result = parse_json(payload)
    assert isinstance(result.entries[0].content, list)


# ---------------------------------------------------------------------
# content: always a list, HTML and plain text retained side by side.
# ---------------------------------------------------------------------


def test_content_list_keeps_both_html_and_plain_text():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_html": "<p>html</p>",
                "content_text": "plain",
            }
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    content = result.entries[0].content

    assert isinstance(content, list)
    assert len(content) == 2
    html_detail, text_detail = content
    assert html_detail["type"] == "text/html"
    assert html_detail["value"] == "<p>html</p>"
    assert text_detail["type"] == "text/plain"
    assert text_detail["value"] == "plain"
    # Every content variant carries the RSS/Atom detail contract.
    for detail in content:
        assert set(detail) == {"value", "type", "base", "language"}
        assert isinstance(detail, feedparser.FeedParserDict)
        # Attribute access must work like dictionary access.
        assert detail.value == detail["value"]


def test_content_list_with_only_one_variant():
    html_only = parse_json(
        make_feed([{"id": "1", "content_html": "<p>html</p>"}]),
        normalize_json_feeds=True,
    )
    assert [c["type"] for c in html_only.entries[0].content] == ["text/html"]

    text_only = parse_json(
        make_feed([{"id": "1", "content_text": "plain"}]),
        normalize_json_feeds=True,
    )
    assert [c["type"] for c in text_only.entries[0].content] == ["text/plain"]


def test_summary_detail_contract_and_content_fallback():
    with_summary = parse_json(
        make_feed([{"id": "1", "content_text": "body", "summary": "the summary"}]),
        normalize_json_feeds=True,
    )
    detail = with_summary.entries[0].summary_detail
    assert detail["type"] == "text/plain"
    assert detail["value"] == "the summary"
    assert "base" in detail and "language" in detail

    without_summary = parse_json(
        make_feed([{"id": "1", "content_html": "<p>body</p>"}]),
        normalize_json_feeds=True,
    )
    entry = without_summary.entries[0]
    assert entry.summary == entry.content[0]["value"]
    assert entry.summary_detail == entry.content[0]
    assert entry.summary_detail is not entry.content[0]


# ---------------------------------------------------------------------
# HTML sanitization and relative-URI resolution switch combinations.
# ---------------------------------------------------------------------


HTML = '<p>hi <a href="/rel">x</a></p><script>alert(1)</script>'


@pytest.mark.parametrize(
    "sanitize, resolve, expected",
    (
        (True, True, '<p>hi <a href="https://example.org/rel">x</a></p>'),
        (True, False, '<p>hi <a href="/rel">x</a></p>'),
        (
            False,
            True,
            '<p>hi <a href="https://example.org/rel">x</a></p>'
            "<script>alert(1)</script>",
        ),
        (False, False, HTML),
    ),
)
def test_html_respects_sanitize_and_resolve_switches(sanitize, resolve, expected):
    payload = make_feed([{"id": "1", "content_html": HTML}])
    result = parse_json(
        payload,
        normalize_json_feeds=True,
        sanitize_html=sanitize,
        resolve_relative_uris=resolve,
        response_headers={
            "content-type": "application/feed+json",
            "content-location": "https://example.org/feed.json",
        },
    )
    html_detail = result.entries[0].content[0]
    assert html_detail["type"] == "text/html"
    assert html_detail["value"] == expected
    # Plain text is never sanitized or link-rewritten.
    payload_text = make_feed([{"id": "1", "content_text": HTML}])
    text_result = parse_json(
        payload_text,
        normalize_json_feeds=True,
        sanitize_html=sanitize,
        resolve_relative_uris=resolve,
        response_headers={
            "content-type": "application/feed+json",
            "content-location": "https://example.org/feed.json",
        },
    )
    assert text_result.entries[0].content[0]["value"] == HTML


def test_legacy_mode_ignores_the_new_switches_for_html():
    # The legacy path always sanitizes HTML as it did before.
    payload = make_feed([{"id": "1", "content_html": HTML}])
    result = parse_json(payload, sanitize_html=False, resolve_relative_uris=False)
    legacy = result.entries[0].content
    assert legacy["type"] == "html"
    assert "<script>" not in legacy["value"]


def test_base_uses_content_location_header():
    payload = make_feed([{"id": "1", "content_html": '<a href="rel">x</a>'}])
    result = parse_json(
        payload,
        normalize_json_feeds=True,
        response_headers={
            "content-type": "application/feed+json",
            "content-location": "https://example.org/dir/feed.json",
        },
    )
    detail = result.entries[0].content[0]
    assert detail["base"] == "https://example.org/dir/feed.json"
    assert detail["value"] == ('<a href="https://example.org/dir/rel">x</a>')


def test_base_uses_final_redirect_url():
    # Register mocks on the session-level ``responses`` mock started in
    # conftest.py (do not use ``@responses.activate``, whose stop() would
    # tear down the shared patcher for every later HTTP test).
    body = json.dumps(
        make_feed([{"id": "1", "content_html": '<a href="rel">x</a>'}])
    ).encode("utf-8")
    responses.add(
        responses.GET,
        "http://old.example/feed",
        status=302,
        headers={"Location": "http://new.example/feed.json"},
    )
    responses.add(
        responses.GET,
        "http://new.example/feed.json",
        body=body,
        content_type="application/feed+json",
    )

    result = feedparser.parse("http://old.example/feed", normalize_json_feeds=True)

    assert result.href == "http://new.example/feed.json"
    detail = result.entries[0].content[0]
    assert detail["base"] == "http://new.example/feed.json"
    assert detail["value"] == '<a href="http://new.example/rel">x</a>'


def test_content_location_resolves_against_final_redirect_url():
    body = json.dumps(
        make_feed([{"id": "1", "content_html": '<a href="rel">x</a>'}])
    ).encode("utf-8")
    responses.add(
        responses.GET,
        "http://old.example/feed",
        status=302,
        headers={"Location": "http://new.example/dir/feed.json"},
    )
    responses.add(
        responses.GET,
        "http://new.example/dir/feed.json",
        body=body,
        content_type="application/feed+json",
        headers={"Content-Location": "sub/feed.json"},
    )

    result = feedparser.parse("http://old.example/feed", normalize_json_feeds=True)

    detail = result.entries[0].content[0]
    assert detail["base"] == "http://new.example/dir/sub/feed.json"
    assert detail["value"] == ('<a href="http://new.example/dir/sub/rel">x</a>')


# ---------------------------------------------------------------------
# tags, links and enclosures (attachment aliases).
# ---------------------------------------------------------------------


def test_tags_are_dictionaries_with_category_accessor():
    payload = make_feed(
        [{"id": "1", "tags": ["first", "second"]}],
        tags=["feedtag"],
    )
    result = parse_json(payload, normalize_json_feeds=True)

    assert result.feed.tags == [{"term": "feedtag", "scheme": None, "label": None}]
    tags = result.entries[0].tags
    assert tags == [
        {"term": "first", "scheme": None, "label": None},
        {"term": "second", "scheme": None, "label": None},
    ]
    assert all(isinstance(t, feedparser.FeedParserDict) for t in tags)
    # The RSS/Atom-compatible virtual accessors.
    assert result.entries[0]["category"] == "first"
    assert result.entries[0].category == "first"


def test_attachments_become_enclosure_links_and_aliases():
    payload = make_feed(
        [
            {
                "id": "1",
                "url": "https://example.org/post",
                "attachments": [
                    {
                        "url": "https://example.org/a.mp3",
                        "mime_type": "audio/mpeg",
                        "size_in_bytes": 1234,
                    },
                    {
                        "url": "https://example.org/b.png",
                        "mime_type": "image/png",
                    },
                ],
            }
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    entry = result.entries[0]

    # The alternate entry link and the enclosure links share one list.
    assert entry.links == [
        {
            "rel": "alternate",
            "type": "text/html",
            "href": "https://example.org/post",
        },
        {
            "rel": "enclosure",
            "href": "https://example.org/a.mp3",
            "type": "audio/mpeg",
            "length": 1234,
        },
        {
            "rel": "enclosure",
            "href": "https://example.org/b.png",
            "type": "image/png",
        },
    ]
    # The virtual ``enclosures`` accessor derives from ``links`` and
    # strips the ``rel`` attribute, matching the RSS/Atom contract.
    assert entry.enclosures == [
        {
            "href": "https://example.org/a.mp3",
            "type": "audio/mpeg",
            "length": 1234,
        },
        {"href": "https://example.org/b.png", "type": "image/png"},
    ]
    assert "enclosures" not in dict(entry)


def test_feed_links_include_home_page_and_feed_url():
    payload = make_feed(
        [{"id": "1"}],
        home_page_url="https://example.org/",
        feed_url="https://example.org/feed.json",
    )
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.feed.link == "https://example.org/"
    assert result.feed.links == [
        {"rel": "alternate", "type": "text/html", "href": "https://example.org/"},
        {
            "rel": "self",
            "type": "application/feed+json",
            "href": "https://example.org/feed.json",
        },
    ]


def test_feed_description_maps_to_subtitle_without_summary_alias():
    payload = make_feed(
        [{"id": "1", "summary": "entry summary"}],
        description="feed description",
    )
    result = parse_json(payload, normalize_json_feeds=True)
    feed = result.feed

    # Feed-level description follows the Atom contract: subtitle only, with
    # no entry-level ``summary`` key leaking onto the feed object.
    assert "summary" not in dict(feed)
    assert feed.subtitle == "feed description"
    assert feed.subtitle_detail == {
        "value": "feed description",
        "type": "text/plain",
        "base": "",
        "language": None,
    }
    # Entry-level summaries are unaffected.
    assert result.entries[0].summary == "entry summary"


def test_relative_attachment_and_link_uris_resolve_with_the_switch():
    payload = make_feed(
        [
            {
                "id": "1",
                "url": "post",
                "attachments": [{"url": "media/a.mp3", "mime_type": "audio/mpeg"}],
            }
        ]
    )
    headers = {
        "content-type": "application/feed+json",
        "content-location": "https://example.org/dir/feed.json",
    }
    resolved = parse_json(
        payload,
        normalize_json_feeds=True,
        resolve_relative_uris=True,
        response_headers=headers,
    )
    entry = resolved.entries[0]
    assert entry.link == "https://example.org/dir/post"
    assert entry.links[1]["href"] == "https://example.org/dir/media/a.mp3"

    raw = parse_json(
        payload,
        normalize_json_feeds=True,
        resolve_relative_uris=False,
        response_headers=headers,
    )
    assert raw.entries[0].link == "post"
    assert raw.entries[0].links[1]["href"] == "media/a.mp3"


# ---------------------------------------------------------------------
# Authors: 1.1 multi-author, 1.0 single-author fallback, inheritance.
# ---------------------------------------------------------------------


def test_feed_level_multiple_authors_with_primary_synchronization():
    payload = make_feed(
        [{"id": "1"}],
        authors=[
            {"name": "First", "url": "https://example.org/first"},
            {"name": "Second", "url": "mailto:second@example.org"},
        ],
    )
    result = parse_json(payload, normalize_json_feeds=True)
    feed = result.feed

    assert feed.authors == [
        {"name": "First", "href": "https://example.org/first"},
        {"name": "Second", "email": "second@example.org"},
    ]
    assert feed.author == "First"
    assert feed.author_detail == {
        "name": "First",
        "href": "https://example.org/first",
    }


def test_authors_array_takes_precedence_over_single_author():
    payload = make_feed(
        [
            {
                "id": "1",
                "author": {"name": "Single"},
                "authors": [{"name": "Array One"}, {"name": "Array Two"}],
            }
        ],
        author={"name": "Feed Single"},
        authors=[{"name": "Feed Array"}],
    )
    result = parse_json(payload, normalize_json_feeds=True)

    assert [a["name"] for a in result.feed.authors] == ["Feed Array"]
    assert [a["name"] for a in result.entries[0].authors] == [
        "Array One",
        "Array Two",
    ]


def test_json_1_single_author_fallback():
    payload = {
        "version": JSON_10,
        "title": "Old",
        "author": {"name": "Old Author", "url": "mailto:old@example.org"},
        "items": [
            {"id": "1"},
            {"id": "2", "author": {"name": "Item Author"}},
        ],
    }
    result = parse_json(payload, normalize_json_feeds=True)

    assert result.feed.authors == [{"name": "Old Author", "email": "old@example.org"}]
    assert result.feed.author == "Old Author (old@example.org)"
    # Entries without an author inherit the feed-level single author.
    assert result.entries[0].authors == [
        {"name": "Old Author", "email": "old@example.org"}
    ]
    assert result.entries[0].author_detail == {
        "name": "Old Author",
        "email": "old@example.org",
    }
    # Per-entry author overrides the inherited one.
    assert result.entries[1].authors == [{"name": "Item Author"}]
    assert result.entries[1].author == "Item Author"


def test_entry_author_overrides_inherited_feed_authors():
    payload = make_feed(
        [
            {"id": "1"},
            {"id": "2", "authors": [{"name": "Entry Author"}]},
            {"id": "3"},
        ],
        authors=[{"name": "Feed Author"}],
    )
    result = parse_json(payload, normalize_json_feeds=True)
    entries = result.entries

    assert entries[0].authors == [{"name": "Feed Author"}]
    assert entries[1].authors == [{"name": "Entry Author"}]
    assert entries[1].author == "Entry Author"
    assert entries[2].authors == [{"name": "Feed Author"}]


def test_inherited_author_state_is_not_shared_between_entries():
    payload = make_feed(
        [{"id": "1"}, {"id": "2"}],
        authors=[{"name": "Feed Author", "url": "https://example.org/me"}],
    )
    result = parse_json(payload, normalize_json_feeds=True)
    first, second = result.entries

    # Every entry receives independent copies of the inherited objects.
    assert first.authors is not second.authors
    assert first.authors is not result.feed.authors
    assert first.author_detail is not second.author_detail
    assert first.authors == second.authors == result.feed.authors

    # Mutating one entry must not leak into other entries or the feed.
    first.authors[0]["name"] = "MUTATED"
    first.authors.append({"name": "APPENDED"})
    first.author_detail["name"] = "DETAIL MUTATED"

    assert second.authors == [{"name": "Feed Author", "href": "https://example.org/me"}]
    assert second.author_detail == {
        "name": "Feed Author",
        "href": "https://example.org/me",
    }
    assert result.feed.authors == [
        {"name": "Feed Author", "href": "https://example.org/me"}
    ]

    # Re-parsing must produce fresh, unaffected objects as well.
    reparsed = parse_json(payload, normalize_json_feeds=True)
    assert reparsed.entries[0].authors[0]["name"] == "Feed Author"


# ---------------------------------------------------------------------
# Language: per-entry override, default inheritance, isolated state.
# ---------------------------------------------------------------------


def test_language_override_and_inheritance():
    payload = make_feed(
        [
            {"id": "1"},
            {"id": "2", "language": "fr"},
        ],
        language="en",
    )
    result = parse_json(payload, normalize_json_feeds=True)

    assert result.feed.language == "en"
    assert "language" not in result.entries[0]
    # Content details carry the effective language.
    text_payload = make_feed(
        [
            {"id": "1", "content_text": "a"},
            {"id": "2", "language": "fr", "content_text": "b"},
        ],
        language="en",
    )
    text_result = parse_json(text_payload, normalize_json_feeds=True)
    assert text_result.entries[0].content[0]["language"] == "en"
    assert text_result.entries[1].content[0]["language"] == "fr"
    assert text_result.entries[1].language == "fr"


def test_http_content_language_is_the_feed_default():
    payload = make_feed(
        [
            {"id": "1", "content_text": "a"},
            {"id": "2", "language": "de", "content_text": "b"},
        ]
    )
    result = parse_json(
        payload,
        normalize_json_feeds=True,
        response_headers={
            "content-type": "application/feed+json",
            "content-language": "ja",
        },
    )
    assert result.feed.language == "ja"
    assert result.entries[0].content[0]["language"] == "ja"
    assert result.entries[1].content[0]["language"] == "de"
    assert result.entries[1].language == "de"


# ---------------------------------------------------------------------
# Dates: date_modified (1.1) and date_updated (1.0) map to ``updated``.
# ---------------------------------------------------------------------


def test_date_modified_maps_to_updated():
    payload = make_feed(
        [
            {
                "id": "1",
                "date_modified": "2020-01-02T03:04:05Z",
                "date_published": "2019-12-31T23:59:00Z",
            }
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    entry = result.entries[0]

    assert entry.updated == "2020-01-02T03:04:05Z"
    assert entry.updated_parsed[:6] == (2020, 1, 2, 3, 4, 5)
    assert entry.published == "2019-12-31T23:59:00Z"
    assert entry.published_parsed[:6] == (2019, 12, 31, 23, 59, 0)


def test_json_1_date_updated_maps_to_updated():
    payload = {
        "version": JSON_10,
        "title": "Old",
        "items": [{"id": "1", "date_updated": "2020-01-02T03:04:05Z"}],
    }
    result = parse_json(payload, normalize_json_feeds=True)
    entry = result.entries[0]
    assert entry.updated == "2020-01-02T03:04:05Z"
    assert entry.updated_parsed[:6] == (2020, 1, 2, 3, 4, 5)


def test_legacy_date_updated_behavior_is_unchanged():
    # The legacy parser has a pre-existing date_updated bug; it must not
    # silently change while normalization is off.
    payload = {
        "version": JSON_10,
        "title": "Old",
        "items": [{"id": "1", "date_updated": "2020-01-02T03:04:05Z"}],
    }
    result = parse_json(payload)
    assert result.bozo == 1
    assert isinstance(result.bozo_exception, KeyError)
    assert result.entries == []


# ---------------------------------------------------------------------
# Miscellaneous contract details.
# ---------------------------------------------------------------------


def test_standard_fields_and_guid_permalink_flag():
    payload = make_feed(
        [
            {"id": "with-link", "url": "https://example.org/p", "title": "A"},
            {"id": "no-link", "title": "B"},
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    with_link, no_link = result.entries

    assert with_link.id == "with-link"
    assert with_link.guidislink is False
    assert no_link.guidislink is True
    assert with_link.title == "A"
    assert "link" not in no_link


def test_dictionary_and_attribute_access_are_equivalent():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_text": "plain",
                "tags": ["tag"],
                "url": "https://example.org/p",
                "attachments": [
                    {"url": "https://example.org/a.mp3", "mime_type": "audio/mpeg"}
                ],
            }
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    entry = result.entries[0]

    assert entry["content"] == entry.content
    assert entry["tags"] == entry.tags
    assert entry["links"] == entry.links
    assert entry["enclosures"] == entry.enclosures
    assert isinstance(entry, feedparser.FeedParserDict)
    assert isinstance(entry.content[0], feedparser.FeedParserDict)
    assert isinstance(entry.links[0], feedparser.FeedParserDict)


def test_normalized_output_contains_no_bytes():
    payload = make_feed(
        [
            {
                "id": "1",
                "content_text": "plain",
                "content_html": "<p>html</p>",
                "tags": ["t"],
                "authors": [{"name": "A"}],
                "attachments": [
                    {
                        "url": "https://example.org/a",
                        "mime_type": "text/plain",
                        "size_in_bytes": 7,
                    }
                ],
            }
        ],
        authors=[{"name": "FA"}],
    )
    result = parse_json(payload, normalize_json_feeds=True)

    def assert_no_bytes(obj):
        if isinstance(obj, dict):
            for value in obj.values():
                assert_no_bytes(value)
        elif isinstance(obj, list):
            for item in obj:
                assert_no_bytes(item)
        else:
            assert not isinstance(obj, bytes)

    assert_no_bytes(result.feed)
    assert_no_bytes(result.entries)


def test_bozo_on_malformed_json_is_unchanged():
    result = feedparser.parse(
        io.BytesIO(b"{not json"),
        response_headers={"content-type": "application/feed+json"},
        normalize_json_feeds=True,
    )
    assert result.bozo == 1
    assert result.entries == []


def test_unrecognized_version_remains_bozo_in_normalized_mode():
    payload = {"version": "https://jsonfeed.org/version/99", "items": []}
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.bozo == 1
    assert isinstance(result.bozo_exception, ValueError)


def test_copy_deepcopy_roundtrip_preserves_normalized_structure():
    payload = make_feed(
        [{"id": "1", "content_html": "<p>x</p>", "tags": ["t"]}],
        authors=[{"name": "F"}],
    )
    result = parse_json(payload, normalize_json_feeds=True)
    clone = copy.deepcopy(result)
    assert clone.entries[0].content == result.entries[0].content
    assert clone.feed.authors == result.feed.authors


# ---------------------------------------------------------------------
# Robustness against malformed-but-decodable JSON feeds.
# ---------------------------------------------------------------------


def test_empty_authors_array_does_not_crash_and_falls_back():
    payload = make_feed(
        [{"id": "1", "authors": [], "author": {"name": "Fallback"}}],
        authors=[],
        author={"name": "Feed Fallback"},
    )
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.feed.authors == [{"name": "Feed Fallback"}]
    assert result.entries[0].authors == [{"name": "Fallback"}]


def test_invalid_author_and_attachment_values_are_skipped():
    payload = make_feed(
        [
            {
                "id": "1",
                "authors": ["not-an-object", {"name": "Valid"}, 42],
                "attachments": [
                    "not-an-object",
                    {"mime_type": "audio/mpeg"},
                    {"url": "https://example.org/a.mp3"},
                    {
                        "url": "https://example.org/b.mp3",
                        "mime_type": "audio/mpeg",
                        "size_in_bytes": 9,
                    },
                ],
            }
        ]
    )
    result = parse_json(payload, normalize_json_feeds=True)
    entry = result.entries[0]
    assert entry.authors == [{"name": "Valid"}]
    assert entry.author == "Valid"
    assert entry.enclosures == [
        {"href": "https://example.org/b.mp3", "type": "audio/mpeg", "length": 9}
    ]


def test_missing_items_and_non_dict_items_are_handled():
    payload = {"version": JSON_11, "title": "No items key"}
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.bozo is False
    assert result.entries == []

    payload = {
        "version": JSON_11,
        "title": "Mixed items",
        "items": [None, "junk", {"id": "1", "title": "ok"}],
    }
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.bozo is False
    assert [e.id for e in result.entries] == ["1"]


def test_non_string_tags_are_skipped():
    payload = make_feed(
        [{"id": "1", "tags": ["ok", 3, None, {"term": "dict-tag"}]}],
        tags=[1, "feed-ok"],
    )
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.feed.tags == [{"term": "feed-ok", "scheme": None, "label": None}]
    assert result.entries[0].tags == [{"term": "ok", "scheme": None, "label": None}]


def test_empty_string_language_falls_back_to_feed_language():
    payload = make_feed(
        [{"id": "1", "language": "", "content_text": "x"}],
        language="en",
    )
    result = parse_json(payload, normalize_json_feeds=True)
    assert result.entries[0].content[0]["language"] == "en"
