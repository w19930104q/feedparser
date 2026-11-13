.. _geometries:

Geometry Extraction (GeoRSS and GML)
====================================

..  note::

    This feature is opt-in. It is disabled by default, and enabling it does
    not change the existing ``where`` key: everything described here is
    returned *in addition to* the historical results.

Feeds such as weather or emergency alert subscriptions often attach several
geographic areas to a single entry. When the ``geometries`` mode is enabled,
:program:`feedparser` collects every recognized geometry into an ordered list
on the feed and on each entry::

    >>> import feedparser
    >>> result = feedparser.parse("alerts.xml", geometries=True)
    >>> result.feed["geometries"]
    [{'type': 'Point', 'coordinates': (-122.0, 45.0)}]
    >>> result.entries[0]["geometries"]
    [{'type': 'LineString', 'coordinates': [(-122.0, 45.0), (-123.0, 46.0)]}]

To enable the mode for every call, set :data:`feedparser.GEOMETRIES` to ``1``
instead of passing ``geometries=True`` to :func:`feedparser.parse`.

When the mode is disabled (the default), no ``geometries`` or
``geometries_diagnostics`` keys are added and parsing behaves exactly as
before.


Supported elements
------------------

* GeoRSS Simple: ``georss:point``, ``georss:line``, and ``georss:polygon``.
  (``georss:box`` is not a geometry and remains available through ``where``
  only.)
* GML (inside ``georss:where`` or standalone): ``gml:Point``,
  ``gml:LineString``, and ``gml:Polygon``. Polygon exterior *and* interior
  rings are preserved, as are standalone ``gml:LinearRing`` elements, which
  are exposed as single-ring polygons.

Each list item is a GeoJSON-like dictionary:

``Point``
    ``{"type": "Point", "coordinates": (lon, lat)}``
``LineString``
    ``{"type": "LineString", "coordinates": [(lon, lat), ...]}``
``Polygon``
    ``{"type": "Polygon", "coordinates": [[exterior ring], [hole], ...]}``

Coordinates are always emitted as ``(longitude, latitude)`` tuples — or
``(longitude, latitude, altitude)`` for three-dimensional input — matching
the GeoJSON ordering. GeoRSS and GML encode WGS 84 coordinates as
``(lat, lon[, alt])``, so the first two ordinates are swapped for you.


Coordinate reference systems
----------------------------

Only WGS 84 is supported: either an absent ``srsName`` (the GeoRSS default)
or the explicit identifier ``urn:ogc:def:crs:EPSG::4326``. Geometries
declaring any other ``srsName`` are dropped and diagnosed.

Two- and three-dimensional coordinates are supported. ``srsDimension`` may
be ``2`` (the default) or ``3``; altitude is preserved. ``srsName`` and
``srsDimension`` follow element scoping rules: a value declared on an
element applies to that element and its descendants, may be overridden by
a nested element, and never leaks to sibling elements, other geometries,
or other entries.


Validation and diagnostics
--------------------------

Every geometry is validated:

* all coordinates must be finite numbers;
* the coordinate count must match the geometry type (exactly one position
  for a point, at least two for a line);
* every polygon ring must contain at least four positions and must be
  closed (the last position identical to the first).

An invalid geometry is dropped as a whole — a polygon with one bad ring is
dropped entirely — without affecting any other geometry, and a diagnostic
is appended to ``result["geometries_diagnostics"]``::

    >>> result["geometries_diagnostics"]
    [{'entry': 1, 'geometry': 0, 'message': "non-finite coordinate 'nan'"}]

Each diagnostic identifies the entry (its index in ``result["entries"]``,
or ``None`` for feed-level geometries) and the geometry's ordinal within
that feed or entry, counted in document order across both valid and
invalid geometries.

The strict XML parser and the lenient fallback parser produce identical
``geometries`` lists and diagnostics.
