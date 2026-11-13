# Offline tests for RFC 6721 Atom tombstone (deleted-entry) support.
#
# These tests exercise both the strict SAX parser and the loose SGML parser
# (the latter via the ``use_loose_parser`` fixture) and require no network.
from __future__ import annotations

import pytest

import feedparser


TOMB_NS = "http://purl.org/atompub/tombstones/1.0"


@pytest.fixture(params=["strict", "loose"])
def parse(request, monkeypatch):
    """Return a parse() bound to the strict or loose XML parser."""

    import feedparser.api

    if request.param == "loose":
        monkeypatch.setattr(feedparser.api, "_XML_AVAILABLE", False)
    else:
        monkeypatch.setattr(feedparser.api, "_XML_AVAILABLE", True)
    return feedparser.parse


def _result(parse, text, **kwargs):
    return parse(text, atom_tombstones=True, **kwargs)


def test_disabled_by_default_keeps_legacy_output():
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <entry><id>e1</id></entry>
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:source><id>s1</id><link href="/leak"/></tomb:source>
        <x:junk xmlns:x="http://example.com/x">drop</x:junk>
      </tomb:deleted-entry>
      <entry><id>e2</id></entry>
    </feed>"""

    result = feedparser.parse(text)

    assert "deleted_entries" not in result
    assert "tombstone_diagnostics" not in result
    assert result.bozo is False
    assert [entry.id for entry in result.entries] == ["e1", "e2"]
    # Tombstone contents must not leak into feed or entry dictionaries.
    assert "link" not in result.feed
    assert "links" not in result.feed
    assert all("x_junk" not in entry for entry in result.entries)
    assert all("atomtomb_deleted_entry" not in entry for entry in result.entries)
    assert "atomtomb_deleted_entry" not in result.feed


def test_tombstone_inside_feed_is_separate_from_entries(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <title>Feed</title>
      <entry><id>e1</id><title>First</title></entry>
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z"/>
      <entry><id>e2</id><title>Second</title></entry>
    </feed>"""

    result = _result(parse, text)

    assert result.bozo is False
    assert [entry.id for entry in result.entries] == ["e1", "e2"]
    assert len(result.deleted_entries) == 1
    tomb = result.deleted_entries[0]
    assert tomb.ref == "r1"
    assert tomb.when == "2026-10-01T12:00:00Z"
    parsed = tomb.when_parsed
    assert (parsed.tm_year, parsed.tm_mon, parsed.tm_mday) == (2026, 10, 1)
    assert (parsed.tm_hour, parsed.tm_min, parsed.tm_sec) == (12, 0, 0)


def test_standalone_tombstone_document(parse):
    text = (
        '<?xml version="1.0"?>\n'
        f'<deleted-entry xmlns="{TOMB_NS}" '
        'ref="urn:uuid:1" when="2026-11-01T08:30:00Z">\n'
        '  <link href="http://example.com/gone" rel="alternate" type="text/html"/>\n'
        "  <by><name>Bob</name><email>bob@example.com</email></by>\n"
        "  <comment>removed by publisher</comment>\n"
        "  <source><id>urn:source</id><title>Origin</title></source>\n"
        "</deleted-entry>"
    )

    result = _result(parse, text)

    assert result.bozo is False
    assert result.entries == []
    assert result.version in ("", None)
    assert len(result.deleted_entries) == 1
    tomb = result.deleted_entries[0]
    assert tomb.ref == "urn:uuid:1"
    assert tomb.by == "Bob"
    assert tomb.by_detail.name == "Bob"
    assert tomb.by_detail.email == "bob@example.com"
    assert tomb.comment == "removed by publisher"
    assert tomb.comment_detail.value == "removed by publisher"
    assert tomb.source.id == "urn:source"
    assert tomb.source.title == "Origin"
    assert tomb.links[0].href == "http://example.com/gone"


def test_standalone_tombstone_with_atom_namespaced_children(parse):
    # A standalone tombstone document declares the tombstone namespace as
    # its default, but RFC 6721 requires link/source to use the Atom
    # namespace, which must therefore be declared with its own prefix.
    text = (
        '<?xml version="1.0"?>\n'
        f'<deleted-entry xmlns="{TOMB_NS}" '
        'xmlns:a="http://www.w3.org/2005/Atom" '
        'ref="urn:uuid:2" when="2026-11-02T08:30:00Z">\n'
        '  <a:link href="http://example.com/gone" rel="alternate"/>\n'
        "  <by><name>Bob</name></by>\n"
        "  <a:source><a:id>urn:src</a:id><a:title>Origin</a:title></a:source>\n"
        "</deleted-entry>"
    )

    result = _result(parse, text)

    assert result.entries == []
    tomb = result.deleted_entries[0]
    assert tomb.ref == "urn:uuid:2"
    assert tomb.by == "Bob"
    assert tomb.links[0].href == "http://example.com/gone"
    assert tomb.source.id == "urn:src"
    assert tomb.source.title == "Origin"


def test_non_standard_prefix_is_normalized(parse):
    # The tombstone namespace is declared with an arbitrary prefix; the
    # parser must still recognize it via its namespace URI.
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:zzz="{TOMB_NS}">
      <zzz:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <zzz:by><name>Carol</name></zzz:by>
        <zzz:comment>gone</zzz:comment>
      </zzz:deleted-entry>
    </feed>"""

    result = _result(parse, text)

    assert result.bozo is False
    assert result.namespaces["atomtomb"] == TOMB_NS
    assert len(result.deleted_entries) == 1
    tomb = result.deleted_entries[0]
    assert tomb.ref == "r1"
    assert tomb.by == "Carol"
    assert tomb.comment == "gone"


def test_ref_is_preserved_verbatim(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}" xml:base="http://example.com/feed/">
      <tomb:deleted-entry ref="relative-id" when="2026-10-01T12:00:00Z"/>
    </feed>"""

    result = _result(parse, text)

    # The ref identifies the original entry and must not be resolved
    # against the feed's base URI.
    assert result.deleted_entries[0].ref == "relative-id"


def test_links_resolve_relative_uris_and_inherit_options(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}" xml:base="http://example.com/feed/">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:link href="gone/r1" rel="alternate" type="text/html"/>
        <tomb:link href="gone/r1.atom" rel="edit"/>
      </tomb:deleted-entry>
    </feed>"""

    result = _result(parse, text, resolve_relative_uris=True)

    hrefs = [link.href for link in result.deleted_entries[0].links]
    assert hrefs == [
        "http://example.com/feed/gone/r1",
        "http://example.com/feed/gone/r1.atom",
    ]
    assert result.deleted_entries[0].link == "http://example.com/feed/gone/r1"


def test_comment_is_rich_text_with_base_language_and_sanitization(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}"
        xml:base="http://example.com/feed/" xml:lang="en">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:comment type="html">
          &lt;a href="relative/"&gt;ok&lt;/a&gt;
          &lt;script&gt;alert(1)&lt;/script&gt;
        </tomb:comment>
      </tomb:deleted-entry>
    </feed>"""

    result = _result(parse, text, sanitize_html=True, resolve_relative_uris=True)
    tomb = result.deleted_entries[0]

    assert "<script>" not in tomb.comment
    assert 'href="http://example.com/feed/relative/"' in tomb.comment
    detail = tomb.comment_detail
    assert detail.type == "text/html"
    assert detail.language == "en"
    assert detail.base == "http://example.com/feed/"
    assert detail.value == tomb.comment


def test_comment_respects_sanitize_and_resolve_options(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}"
        xml:base="http://example.com/feed/">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:comment type="html">
          &lt;script&gt;danger()&lt;/script&gt;&lt;a href="r/"&gt;x&lt;/a&gt;
        </tomb:comment>
      </tomb:deleted-entry>
    </feed>"""

    result = _result(
        parse, text, sanitize_html=False, resolve_relative_uris=False
    )
    comment = result.deleted_entries[0].comment

    # With sanitization disabled the dangerous markup is retained, and with
    # relative-URI resolution disabled the in-markup link stays relative.
    assert "<script>danger()</script>" in comment
    assert 'href="r/"' in comment


def test_comment_supports_xhtml_and_plain_text(parse):
    xhtml = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:comment type="xhtml">
          <div xmlns="http://www.w3.org/1999/xhtml"><b>hi</b></div>
        </tomb:comment>
      </tomb:deleted-entry>
    </feed>"""
    result = _result(parse, xhtml)
    assert result.deleted_entries[0].comment_detail.type == "application/xhtml+xml"
    assert "<b>hi</b>" in result.deleted_entries[0].comment

    plain = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <tomb:deleted-entry ref="r2" when="2026-10-01T12:00:00Z">
        <tomb:comment>plain &amp; simple</tomb:comment>
      </tomb:deleted-entry>
    </feed>"""
    result = _result(parse, plain)
    assert result.deleted_entries[0].comment == "plain & simple"
    assert result.deleted_entries[0].comment_detail.type == "text/plain"


def test_nested_source_is_captured_and_isolated(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}" xml:base="http://example.com/feed/">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:source xml:base="origin/">
          <id>urn:origin</id>
          <title>Origin Feed</title>
          <link href="feed.atom" rel="self"/>
          <x:foreign xmlns:x="http://example.com/x">ignore me</x:foreign>
        </tomb:source>
      </tomb:deleted-entry>
    </feed>"""

    result = _result(parse, text)
    source = result.deleted_entries[0].source

    assert source.id == "urn:origin"
    assert source.title == "Origin Feed"
    assert source.links[0].href == "http://example.com/feed/origin/feed.atom"
    # Unknown extensions inside the source are discarded.
    assert "x_foreign" not in source
    # Nothing from the tombstone's source leaks into the feed.
    assert "link" not in result.feed


def test_rfc_compliant_atom_namespaced_link_and_source(parse):
    # RFC 6721 puts ``link`` and ``source`` in the Atom namespace while
    # ``by``/``comment`` live in the tombstone namespace. The unprefixed
    # Atom elements must still be collected inside the tombstone rather than
    # flattened into it or leaked into the feed.
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}" xml:base="http://example.com/feed/">
      <entry><id>e1</id></entry>
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <link href="gone/r1" rel="alternate" type="text/html"/>
        <tomb:by><name>Bob</name></tomb:by>
        <tomb:comment>why</tomb:comment>
        <source>
          <id>urn:origin</id>
          <title>Origin Feed</title>
          <link href="origin.atom" rel="self"/>
        </source>
      </tomb:deleted-entry>
      <entry><id>e2</id></entry>
    </feed>"""

    result = _result(parse, text)
    tomb = result.deleted_entries[0]

    # The tombstone-level link is separate from the source's links.
    assert [link.rel for link in tomb.links] == ["alternate"]
    assert tomb.link == "http://example.com/feed/gone/r1"
    # The Atom-namespaced source is nested, with its own links and fields.
    source = tomb.source
    assert source.id == "urn:origin"
    assert source.title == "Origin Feed"
    assert source.links[0].href == "http://example.com/feed/origin.atom"
    # Nothing from the tombstone leaks into the feed or regular entries.
    assert "link" not in result.feed
    assert all("source" not in entry for entry in result.entries)
    assert [entry.id for entry in result.entries] == [
        "http://example.com/feed/e1",
        "http://example.com/feed/e2",
    ]


def test_bad_tombstones_between_entries_go_to_diagnostics(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <entry><id>e1</id></entry>
      <tomb:deleted-entry when="2026-10-01T12:00:00Z">
        <tomb:comment>missing ref</tomb:comment>
      </tomb:deleted-entry>
      <entry><id>e2</id></entry>
      <tomb:deleted-entry ref="r-bad-when" when="not-a-date"/>
      <entry><id>e3</id></entry>
      <tomb:deleted-entry ref="r-good" when="2026-10-03T12:00:00Z"/>
    </feed>"""

    result = _result(parse, text)

    # The three regular entries survive untouched, in order, and bad
    # tombstones do not set the bozo flag.
    assert result.bozo is False
    assert [entry.id for entry in result.entries] == ["e1", "e2", "e3"]
    assert [tomb.ref for tomb in result.deleted_entries] == ["r-good"]

    diagnostics = result.tombstone_diagnostics
    assert len(diagnostics) == 2
    assert "ref" in diagnostics[0]["reason"]
    assert diagnostics[0].when == "2026-10-01T12:00:00Z"
    assert "when" in diagnostics[1]["reason"]
    assert diagnostics[1].ref == "r-bad-when"
    # The malformed tombstone's content must not attach to the neighbor.
    assert "comment" not in result.entries[1]


def test_repeated_refs_keep_source_order_without_deduplication(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <tomb:deleted-entry ref="dup" when="2026-10-01T12:00:00Z"/>
      <tomb:deleted-entry ref="other" when="2026-10-02T12:00:00Z"/>
      <tomb:deleted-entry ref="dup" when="2026-10-03T12:00:00Z"/>
    </feed>"""

    result = _result(parse, text)

    assert [tomb.ref for tomb in result.deleted_entries] == [
        "dup",
        "other",
        "dup",
    ]
    assert [tomb.when for tomb in result.deleted_entries] == [
        "2026-10-01T12:00:00Z",
        "2026-10-02T12:00:00Z",
        "2026-10-03T12:00:00Z",
    ]


def test_unknown_extensions_are_ignored(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}" xmlns:x="http://example.com/x">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <x:weird attr="v">foreign text</x:weird>
        <x:empty/>
      </tomb:deleted-entry>
    </feed>"""

    result = _result(parse, text)
    tomb = result.deleted_entries[0]

    assert "x_weird" not in tomb
    assert "x_empty" not in tomb
    assert set(tomb.keys()) == {"ref", "when", "when_parsed"}


def test_strict_failure_falls_back_to_loose_without_duplication():
    # An unescaped bare ampersand is fatal for the strict parser but
    # tolerated by the loose one. Parsing must produce each entry/tombstone
    # exactly once across the strict->loose reparse.
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <entry><id>e1</id><title>a & b</title></entry>
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z">
        <tomb:comment>tom & jerry</tomb:comment>
      </tomb:deleted-entry>
      <entry><id>e2</id></entry>
    </feed>"""

    result = feedparser.parse(text, atom_tombstones=True)

    assert result.bozo == 1
    assert [entry.id for entry in result.entries] == ["e1", "e2"]
    assert len(result.entries) == 2
    assert len(result.deleted_entries) == 1
    assert result.deleted_entries[0].ref == "r1"
    assert result.deleted_entries[0].comment == "tom & jerry"
    assert result.tombstone_diagnostics == []


def test_enabled_without_tombstones_exposes_empty_lists(parse):
    text = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>e1</id></entry>
    </feed>"""

    result = _result(parse, text)

    assert result.deleted_entries == []
    assert result.tombstone_diagnostics == []


def test_module_level_flag_defaults_to_off(monkeypatch):
    import feedparser

    monkeypatch.setattr(feedparser, "ATOM_TOMBSTONES", 1, raising=True)
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <tomb:deleted-entry ref="r1" when="2026-10-01T12:00:00Z"/>
    </feed>"""

    result = feedparser.parse(text)
    assert [tomb.ref for tomb in result.deleted_entries] == ["r1"]

    monkeypatch.setattr(feedparser, "ATOM_TOMBSTONES", 0, raising=True)
    result = feedparser.parse(text)
    assert "deleted_entries" not in result


def test_everything_is_unicode(parse):
    text = f"""<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:tomb="{TOMB_NS}">
      <tomb:deleted-entry ref="urn:rï" when="2026-10-01T12:00:00Z">
        <tomb:by><name>Zoé</name></tomb:by>
        <tomb:comment>café</tomb:comment>
      </tomb:deleted-entry>
    </feed>""".encode("utf-8")

    result = _result(parse, text)

    def check(value):
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
        else:
            assert not isinstance(value, bytes)

    check(result.deleted_entries)
    check(result.tombstone_diagnostics)
