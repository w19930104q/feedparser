.. _advanced.atom_tombstones:

Atom Tombstones (RFC 6721)
==========================

Why tombstones matter
---------------------

When an entry disappears from a feed, an aggregator cannot tell from the feed
alone whether the publisher *deleted* the entry or simply stopped including it
in the current window. :rfc:`6721` closes that gap with the Atom tombstone, an
``deleted-entry`` element in the ``http://purl.org/atompub/tombstones/1.0``
namespace.

A tombstone carries, at minimum:

* a ``ref`` attribute identifying the deleted entry, and
* a ``when`` attribute giving the deletion time.

It may additionally carry ``by`` (who deleted it), ``comment`` (why), ``link``
elements and an Atom ``source`` element. A tombstone can appear directly
inside an Atom feed, or it can be the root element of a standalone tombstone
document.

Enabling tombstone support
--------------------------

Tombstone parsing is **off by default** so that existing programs keep exactly
the same output. Enable it per call with the ``atom_tombstones`` argument:

..  code-block:: pycon

    >>> import feedparser
    >>> d = feedparser.parse(feed_bytes, atom_tombstones=True)
    >>> d.deleted_entries
    [...]

You can also flip the global default for the whole process:

..  code-block:: python

    import feedparser
    feedparser.ATOM_TOMBSTONES = 1

When the feature is disabled, ``deleted-entry`` markup is treated as
unrecognized foreign content and never appears anywhere in the result, and the
``deleted_entries`` / ``tombstone_diagnostics`` keys are absent.

Where the data lands
--------------------

Tombstones never alter the regular feed entries. With the feature enabled the
result gains two additional top-level lists:

* ``deleted_entries`` -- the well-formed tombstones, in document order
* ``tombstone_diagnostics`` -- the malformed tombstones that were rejected

Repeated notifications with the same ``ref`` are all retained and stay in the
order they appeared in the document; feedparser does not deduplicate them.

The ``ref`` value is stored unchanged. Relative links and HTML inside the
tombstone still honor the feed's base :abbr:`URI (Uniform Resource Identifier)`,
the effective language, and the ``resolve_relative_uris`` / ``sanitize_html``
options, exactly as they do for normal entries.

Malformed tombstones
--------------------

A tombstone without a ``ref`` or with a ``when`` value that is not a valid date
is rejected. It goes into ``tombstone_diagnostics`` rather than
``deleted_entries``, it does not set the ``bozo`` flag, and it cannot affect
neighboring entries or the feed-level data.

..  code-block:: pycon

    >>> d = feedparser.parse(feed_bytes, atom_tombstones=True)
    >>> d.tombstone_diagnostics
    [{'reason': 'deleted-entry has an invalid when attribute',
      'ref': 'tag:example,2026:entry',
      'when': 'not-a-date'}]

See :ref:`reference.deleted_entries` for the full description of every field.
