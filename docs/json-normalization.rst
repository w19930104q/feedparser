.. _advanced.json_normalization:

JSON Feed Normalization
=======================

By default, `JSON Feed <https://www.jsonfeed.org/>`_ data is exposed using the
historical JSON-specific structure. For example, an entry's ``content`` is a
single dictionary that keeps only one of the HTML or plain-text variants,
``tags`` are exposed as a bare list of strings under ``category``, and
attachments are stored on a separate ``enclosures`` key without a matching
``links`` entry.

Starting with this version, feedparser offers an opt-in *normalized* JSON Feed
mode that makes JSON feeds follow the same contract as RSS and Atom feeds.
Enable it per call::

    >>> import feedparser
    >>> d = feedparser.parse(
    ...     "https://example.org/feed.json",
    ...     normalize_json_feeds=True,
    ... )

or globally for every subsequent call::

    >>> feedparser.NORMALIZE_JSON_FEEDS = 1

The mode is disabled by default, so existing JSON Feed integrations keep
working unchanged. RSS and Atom parsing is never affected by this setting.

What changes in normalized mode
-------------------------------

Content
    ``entry.content`` is always a list of content dictionaries. When a feed
    item provides both ``content_html`` and ``content_text``, both variants
    are retained, the HTML one first, with ``type`` values of ``text/html``
    and ``text/plain``. Every dictionary carries the usual ``value``,
    ``type``, ``base`` and ``language`` keys, just like Atom content.

Tags
    ``tags`` is a list of ``{"term": ..., "scheme": None, "label": None}``
    dictionaries, matching the RSS/Atom tag structure. The virtual
    ``entry.category`` accessor keeps working and returns the first term.

Links and attachments
    The item ``url`` becomes an ``alternate`` link and ``external_url``
    becomes a ``related`` link. Attachments are appended to the same
    ``entry.links`` list with ``rel="enclosure"``, so the virtual
    ``entry.enclosures`` accessor derives from ``links`` exactly as it does
    for RSS and Atom.

Authors
    JSON Feed 1.1's ``authors`` array is fully supported and takes
    precedence over the single JSON Feed 1.0 ``author`` object, which
    remains as a single-author fallback. The singular ``author`` and
    ``author_detail`` fields are synchronized with the first author. Items
    without their own author inherit the feed-level authors, and every item
    receives independent copies so that mutating one entry never affects
    another entry or the feed.

Dates
    JSON Feed 1.1's ``date_modified`` and JSON Feed 1.0's ``date_updated``
    both map to ``updated``/``updated_parsed``; ``date_published`` maps to
    ``published``/``published_parsed`` as before.

Language
    An item-level ``language`` overrides the feed-level language, which
    itself defaults to the HTTP ``Content-Language`` response header. The
    effective language is recorded on each content dictionary, and entries
    without their own language inherit the feed default.

HTML processing, base URIs and the parse switches
-------------------------------------------------

Normalized HTML content honors the same :py:func:`feedparser.parse` switches as
RSS and Atom content:

*   pass ``sanitize_html=False`` to keep potentially dangerous markup, and
*   pass ``resolve_relative_uris=False`` to keep relative links untouched.

Relative links are resolved against the same base URI rules used for XML
feeds: the final response URL after redirects is combined with the HTTP
``Content-Location`` response header, if present. The resolved base is also
recorded in each content dictionary's ``base`` key. Plain-text content is
neither sanitized nor link-rewritten.
