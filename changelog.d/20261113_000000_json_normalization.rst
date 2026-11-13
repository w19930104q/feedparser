Added
-----

*   Add an opt-in normalized JSON Feed mode, enabled with
    ``feedparser.parse(..., normalize_json_feeds=True)`` or by setting
    ``feedparser.NORMALIZE_JSON_FEEDS`` to a true value.

    In normalized mode JSON feeds follow the same RSS/Atom contract:

    *   ``content`` is always a list that retains both the HTML and plain-text
        variants, each with ``value``, ``type``, ``base`` and ``language``.
    *   ``tags`` is a list of ``term``/``scheme``/``label`` dictionaries.
    *   Attachments are exposed as ``enclosure`` entries in ``links``, so the
        ``enclosures`` virtual accessor works like it does for RSS and Atom.
    *   JSON Feed 1.1 ``authors`` arrays are supported, with the JSON Feed 1.0
        single ``author`` object as a fallback; entries without an author
        inherit independent copies of the feed-level authors.
    *   ``date_modified`` (1.1) and ``date_updated`` (1.0) both map to
        ``updated``/``updated_parsed``.
    *   Item-level ``language`` overrides the feed-level language, which
        defaults to the ``Content-Language`` response header.
    *   HTML content honors the ``sanitize_html`` and
        ``resolve_relative_uris`` parse switches, with relative links
        resolved against the final response URL and ``Content-Location``.

    The mode is disabled by default, and the legacy JSON Feed output as well
    as all RSS and Atom behavior are unchanged.
