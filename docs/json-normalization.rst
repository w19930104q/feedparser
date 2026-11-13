.. _advanced.json_normalization:

JSON Feed Normalization
=======================

Historically, JSON feeds were normalized differently from RSS and Atom feeds.
For example, an entry's ``content`` was a single dictionary instead of a list,
its ``type`` used the non-standard values ``"text"`` and ``"html"``, tags were
only available through the ``category`` alias, and attachments were only
available through the ``enclosures`` alias.

Passing ``normalize_json=True`` to ``feedparser.parse()`` makes JSON Feed 1
and 1.1 feeds use the *same* output shapes as the RSS and Atom parsers. The
option is opt-in and defaults to ``False``, so the historical JSON output and
all XML parsing behavior remain unchanged when it is not used.

..  code-block:: pycon

    >>> import feedparser
    >>> d = feedparser.parse("feed.json", normalize_json=True)

``content`` is always a list
-----------------------------

Each entry's ``content`` is a list of dictionaries. The ``type`` values are
standard MIME types (``text/plain`` and ``text/html``), and every dictionary
carries the ``value``, ``type``, ``base`` and ``language`` keys that XML
content dictionaries carry.

When an entry contains both ``content_text`` and ``content_html``, both bodies
are retained: the plain text body comes first and the HTML body second.

..  code-block:: pycon

    >>> entry.content
    [{'base': 'https://example.org/feed.json',
      'language': None,
      'type': 'text/plain',
      'value': 'plain text body'},
     {'base': 'https://example.org/feed.json',
      'language': None,
      'type': 'text/html',
      'value': '<p>HTML body</p>'}]

Plain text bodies and the entry ``id`` are never rewritten. HTML bodies are
processed with the :ref:`sanitization <advanced.sanitization>` and
:ref:`relative URI <advanced.base>` settings of the parse:

*   relative URIs inside the HTML are resolved against the feed's base URI
    (the ``Content-Location`` response header or the feed URL) when
    ``resolve_relative_uris`` is enabled;
*   the HTML is sanitized when ``sanitize_html`` is enabled.

If no valid base URI is available, relative URIs in the HTML are left
untouched.

Tags
----

JSON Feed ``tags`` become the same ``tags`` list that XML feeds produce, and
the dynamic ``category`` alias keeps returning the first tag's term.

..  code-block:: pycon

    >>> entry.tags
    [{'term': 'one', 'scheme': None, 'label': None},
     {'term': 'two', 'scheme': None, 'label': None}]
    >>> entry.category
    'one'

Attachments, links and enclosures
---------------------------------

Entry attachments are added to ``links`` with ``rel`` set to
``"enclosure"``, exactly like XML enclosures. The entry's own ``url`` becomes
an ``alternate`` link. The dynamic ``enclosures`` alias, which omits the
``rel`` key, keeps working and is computed from ``links``.

..  code-block:: pycon

    >>> entry.links
    [{'rel': 'alternate', 'type': 'text/html',
      'href': 'https://example.org/post'},
     {'rel': 'enclosure', 'href': 'https://example.org/a.mp4',
      'type': 'video/mp4', 'length': '123'}]
    >>> entry.enclosures
    [{'href': 'https://example.org/a.mp4',
      'type': 'video/mp4', 'length': '123'}]

Note that enclosure ``length`` is always a string, matching the XML output.

Authors
-------

Authors are always exposed through the ``authors`` list; JSON Feed 1's single
``author`` object is treated as a one-element list. The singular ``author``
and ``author_detail`` fields are kept in sync with the last author, as they
are for XML feeds. A ``mailto:`` author URL becomes the ``email`` key; any
other author URL becomes the ``href`` key.

An entry without an ``authors`` (or legacy ``author``) field inherits a
**deep copy** of the feed-level authors. An explicitly empty ``authors`` list
does not inherit anything, and entries never share author objects with the
feed or with sibling entries.

Dates
-----

The JSON Feed ``date_modified`` field populates ``updated`` and
``updated_parsed``. The parsed value is a 9-tuple in UTC, just like the
parsed dates produced from XML feeds.

..  code-block:: pycon

    >>> entry.updated
    '2020-01-02T03:04:05+02:00'
    >>> entry.updated_parsed
    (2020, 1, 2, 1, 4, 5, 3, 2, 0)
