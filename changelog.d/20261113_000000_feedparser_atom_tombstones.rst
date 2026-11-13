Added
-----

*   Add optional support for :rfc:`6721` Atom tombstone
    (``deleted-entry``) elements.

    Pass ``atom_tombstones=True`` to ``feedparser.parse()`` (or set
    ``feedparser.ATOM_TOMBSTONES = 1``) to collect tombstones that appear
    inside an Atom feed or as a standalone tombstone document into a new
    top-level ``deleted_entries`` list. Each tombstone preserves its original
    ``ref`` and exposes ``when``/``when_parsed``, ``by``/``by_detail``,
    ``comment``/``comment_detail``, ``link``/``links`` and ``source``.
    Relative links and rich text follow the existing base-URI, language,
    HTML-sanitization and relative-URI options, and regular ``entries`` are
    never modified.

    Tombstones that are missing a ``ref`` or carry an unparseable ``when``
    are quarantined in a separate ``tombstone_diagnostics`` list instead of
    polluting the feed or neighboring entries. Unknown extensions are
    ignored, repeated notifications with the same ``ref`` keep their source
    order, and the feature stays fully opt-in so output is unchanged when it
    is disabled.
