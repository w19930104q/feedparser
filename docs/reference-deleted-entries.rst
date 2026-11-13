.. _reference.deleted_entries:

``deleted_entries``
===================

.. note::

    Parsing :rfc:`6721` Atom tombstone elements is **opt-in**. The lists
    documented on this page are only present in the parsed result when
    tombstone support is enabled by passing ``atom_tombstones=True`` to
    ``feedparser.parse()`` or by setting
    ``feedparser.ATOM_TOMBSTONES`` to ``1``.

Atom publishers sometimes need to state explicitly that an entry has been
deleted, rather than merely omitting it from the current feed. :rfc:`6721`
defines the Atom tombstone ``deleted-entry`` element for exactly this
purpose. It lets an aggregator distinguish "this entry was deliberately
removed" from "this entry is simply not in this feed right now".

When tombstone support is enabled, ``deleted-entry`` elements found either as
children of an Atom feed or as the root element of a standalone tombstone
document are collected in a top-level ``deleted_entries`` list. Tombstones are
kept entirely separate from the regular entries; regular entries are
never removed, reordered, or modified because of a tombstone.

Tombstones that are missing a ``ref`` attribute or that carry an unparseable
``when`` attribute are not added to ``deleted_entries``. They are quarantined
in the separate ``tombstone_diagnostics`` list instead, so a malformed
tombstone can never pollute the feed or the entries surrounding it.

Foreign (unknown) markup inside a tombstone is ignored.


``deleted_entries[i].ref``
--------------------------

The original identifier of the entry that was deleted. This is the value of
the tombstone's ``ref`` attribute, preserved verbatim. In particular it is not
resolved against the feed's base :abbr:`URI (Uniform Resource Identifier)`,
since it identifies the original entry rather than locating a resource.


.. _reference.deleted_entries.when:

``deleted_entries[i].when``
---------------------------

The date and time at which the entry was deleted, as the original string from
the tombstone's ``when`` attribute.

A tombstone whose ``when`` value cannot be parsed as a date is treated as
malformed and moved to ``tombstone_diagnostics``.


.. _reference.deleted_entries.when_parsed:

``deleted_entries[i].when_parsed``
----------------------------------

The value of :ref:`reference.deleted_entries.when` parsed into a standard
:program:`Python` 9-tuple, using the same date handling as every other date in
feedparser. See :ref:`advanced.date`.


``deleted_entries[i].by``
-------------------------

The name of the person or entity that deleted the entry, taken from the
tombstone's :rfc:`6721` ``by`` Person construct. Only present when the
tombstone includes a ``by`` element with a ``name``.


``deleted_entries[i].by_detail``
--------------------------------

A dictionary containing the full Person construct from the ``by`` element. It
may contain any of:

* ``name`` -- the display name
* ``href`` -- a :abbr:`URI (Uniform Resource Identifier)`, resolved against
  the base :abbr:`URI (Uniform Resource Identifier)` when relative
* ``email`` -- an email address


.. _reference.deleted_entries.comment:

``deleted_entries[i].comment``
------------------------------

A human-readable comment explaining the deletion, taken from the tombstone's
:rfc:`6721` ``comment`` Atom Text construct.

Because ``comment`` is an Atom Text construct, it follows the same rules as
entry titles and summaries: it is :ref:`sanitized
<advanced.sanitization>` when it contains HTML, and relative
:abbr:`URI (Uniform Resource Identifier)`\s inside its markup are
:ref:`resolved according to a set of rules <advanced.base>`. Both behaviors can
be controlled with the ``sanitize_html`` and ``resolve_relative_uris``
arguments to ``feedparser.parse()``.


``deleted_entries[i].comment_detail``
-------------------------------------

A dictionary containing details about the :ref:`comment
<reference.deleted_entries.comment>` Text construct:

* ``value`` -- the processed comment text, equal to
  ``deleted_entries[i].comment``
* ``type`` -- the content type (``text/plain``, ``text/html`` or
  ``application/xhtml+xml``)
* ``language`` -- the effective language, inherited from ``xml:lang``
* ``base`` -- the effective base :abbr:`URI (Uniform Resource Identifier)`


``deleted_entries[i].link`` and ``deleted_entries[i].links``
------------------------------------------------------------

``links`` is a list of dictionaries describing the tombstone's ``link``
elements, in document order. Each dictionary carries the same ``rel``,
``type`` and ``href`` keys that entry links do, with relative ``href`` values
resolved against the base :abbr:`URI (Uniform Resource Identifier)`.

``link`` is the href of the primary alternate link, when one exists.


``deleted_entries[i].source``
-----------------------------

A dictionary describing the Atom ``source`` element embedded in the tombstone,
i.e. the feed the deleted entry originally came from. It uses the same shape
as :ref:`reference.entry.source`, including ``id``, ``title``, ``links`` and
the related ``*_detail`` dictionaries. Unknown extensions inside the source
are ignored.


.. _reference.tombstone_diagnostics:

``tombstone_diagnostics``
=========================

A list of dictionaries describing tombstones that could not be accepted. A
tombstone is rejected, without setting the ``bozo`` flag, when:

* it has no ``ref`` attribute (or the value is empty), or
* its ``when`` attribute is missing or cannot be parsed as a date.

Each diagnostic dictionary contains:

* ``reason`` -- a short human-readable explanation
* ``ref`` -- the raw ``ref`` value (an empty string when missing)
* ``when`` -- the raw ``when`` value (an empty string when missing)

Entries in this list preserve the document order of the tombstones they
describe.
