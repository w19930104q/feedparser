.. _advanced.geometries:

GeoRSS Geometries
=================

:program:`Universal Feed Parser` recognizes the GeoRSS Simple and GML
geometry elements defined by the ``http://www.georss.org/georss`` and
``http://www.opengis.net/gml`` namespaces: ``Point``, ``LineString`` and
``Polygon`` (GeoRSS Simple calls them ``point``, ``line`` and ``polygon``).


The historical ``where`` result
-------------------------------

For backwards compatibility every feed and entry exposes the *last*
geometry encountered on it through ``where``. When a message contains more
than one location, each successive geometry overwrites the previous one, so
only the final location is retained::

    >>> import feedparser
    >>> feed = '''
    ... <feed xmlns="http://www.w3.org/2005/Atom"
    ...       xmlns:georss="http://www.georss.org/georss">
    ...   <entry>
    ...     <georss:point>45.0 -100.0</georss:point>
    ...     <georss:point>46.0 -101.0</georss:point>
    ...   </entry>
    ... </feed>'''
    >>> d = feedparser.parse(feed)
    >>> d.entries[0].where.coordinates
    (-101.0, 46.0)

This behavior is preserved unchanged.


Collecting every geometry
-------------------------

To keep *all* the locations in a message, pass ``collect_geometries=True``
to :func:`feedparser.parse`. Every valid geometry is then appended to a
``geometries`` list on the feed or entry, in the order in which it appears
in the document::

    >>> d = feedparser.parse(feed, collect_geometries=True)
    >>> d.entries[0].geometries
    [{'type': 'Point', 'coordinates': (-100.0, 45.0)},
     {'type': 'Point', 'coordinates': (-101.0, 46.0)}]

The feature is opt-in and disabled by default. It can also be enabled
globally by setting the :data:`feedparser.COLLECT_GEOMETRIES` module
variable to ``1``; an explicit ``collect_geometries`` keyword argument
always takes precedence over the module variable.

Each geometry is a dictionary with a ``type`` string and a
``coordinates`` value:

*   ``Point`` -- a single ``(longitude, latitude)`` tuple.
*   ``LineString`` -- a tuple of ``(longitude, latitude)`` tuples.
*   ``Polygon`` -- a tuple of rings; the first ring is the exterior ring
    and every subsequent ring is an interior ring (a hole). Each ring is a
    tuple of ``(longitude, latitude)`` tuples whose first and last
    positions are identical.

``georss:box`` bounding boxes remain available through ``where`` but are
not geometry types, so they are never added to ``geometries``.


Coordinate reference systems
----------------------------

All output coordinates are two-dimensional ``(longitude, latitude)``
tuples of Python floats. No projection or datum conversion is ever
performed; only coordinate order is normalized.

Two coordinate reference systems are recognized, each by its standard URN
and HTTP identifiers:

*   **EPSG:4326** -- source coordinates are ordered latitude first, so the
    two components are swapped on output. This is also the default when an
    element carries no ``srsName`` attribute, as used by GeoRSS Simple.
*   **OGC CRS84** -- source coordinates are already ordered longitude
    first, so they pass through unchanged.

The recognized identifiers are::

    urn:ogc:def:crs:EPSG::4326
    urn:ogc:def:crs:EPSG:6.6:4326
    urn:ogc:def:crs:EPSG:6.11:4326
    urn:ogc:def:crs:EPSG:6.18:4326
    http://www.opengis.net/def/crs/EPSG/0/4326
    http://www.opengis.net/gml/srs/epsg.xml#4326
    urn:ogc:def:crs:OGC::CRS84
    urn:ogc:def:crs:OGC:1.3:CRS84
    http://www.opengis.net/def/crs/OGC/1.3/CRS84

An element without an ``srsName`` inherits the nearest ancestor
``srsName``; an explicit attribute (even an unknown one) overrides the
inherited value. Each geometry resolves its own reference system
independently.


Validation and diagnostics
--------------------------

Geometries are validated independently. A geometry is rejected, in full,
when any of the following hold:

*   its ``srsName`` identifies an unknown, projected or
    three-dimensional coordinate reference system;
*   it is not two-dimensional;
*   a coordinate is missing, non-numeric or not a finite number;
*   a longitude or latitude is outside the valid range
    (``[-180, 180]`` / ``[-90, 90]``);
*   a coordinate tuple is incomplete;
*   a line contains fewer than two points;
*   a polygon ring contains fewer than four positions, or is not explicitly
    closed (its last position does not equal its first).

Rejected geometries are simply omitted from ``geometries`` and can never
affect neighboring geometries or other entries. Each rejection emits a
:class:`feedparser.GeometryWarning` whose message identifies the entry (by
its zero-based index, or ``the feed`` for feed-level geometries) and the
one-based position of the geometry within that context::

    Rejected GeoRSS geometry #3 on entry 0: invalid GeoRSS Simple LineString

The legacy ``where`` result is never affected by this validation: it keeps
its historical, more permissive behavior.

Both the strict XML parser and the loose (HTML-tolerant) parser support
geometry collection, including feeds that fall back from the strict parser
to the loose parser.
