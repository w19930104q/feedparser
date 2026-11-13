"""Offline regression tests for the opt-in ``geometries`` GeoRSS result.

The historical ``where`` result keeps only the last geometry of each
message. When ``collect_geometries`` is enabled every valid GeoRSS Simple
and GML geometry is instead appended to a context-level ``geometries``
list, in document order. Invalid geometries are rejected individually with
a :class:`~feedparser.exceptions.GeometryWarning` and can never affect
neighboring geometries or other entries.

These tests parse inline XML strings, so they never touch the network.
Each test runs against both the strict SAX parser and the loose SGML
parser.
"""

from __future__ import annotations

import warnings

import pytest

import feedparser
import feedparser.api
from feedparser.exceptions import GeometryWarning

ATOM_HEADER = (
    '<feed xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:georss="http://www.georss.org/georss" '
    'xmlns:gml="http://www.opengis.net/gml">'
)


@pytest.fixture
def parse():
    """Return a parse() callable; tests select a parser via their parameter."""

    original = feedparser.api._XML_AVAILABLE

    def _parse(xml, parser="strict", **kwargs):
        feedparser.api._XML_AVAILABLE = parser == "strict"
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            return feedparser.parse(xml, **kwargs)

    yield _parse
    feedparser.api._XML_AVAILABLE = original


def parse_with_warnings(xml, parser):
    original = feedparser.api._XML_AVAILABLE
    feedparser.api._XML_AVAILABLE = parser == "strict"
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = feedparser.parse(xml, collect_geometries=True)
    finally:
        feedparser.api._XML_AVAILABLE = original
    geometry_warnings = [
        str(item.message)
        for item in caught
        if issubclass(item.category, GeometryWarning)
    ]
    return result, geometry_warnings


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_disabled_by_default(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>45.0 -100.0</georss:point>"
        + "<georss:point>46.0 -101.0</georss:point>"
        + "</entry></feed>"
    )
    result = parse(xml, parser=parser)
    assert "geometries" not in result.entries[0]
    # The legacy where result is unchanged and keeps the last geometry.
    assert result.entries[0]["where"] == {
        "type": "Point",
        "coordinates": (-101.0, 46.0),
    }


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_explicitly_disabled(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry><georss:point>45.0 -100.0</georss:point></entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=False)
    assert "geometries" not in result.entries[0]


def test_module_level_flag(monkeypatch):
    xml = (
        ATOM_HEADER
        + "<entry><georss:point>45.0 -100.0</georss:point></entry></feed>"
    )
    monkeypatch.setattr(feedparser, "COLLECT_GEOMETRIES", 1)
    result = feedparser.parse(xml)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)}
    ]
    # An explicit keyword argument wins over the module-level flag.
    result = feedparser.parse(xml, collect_geometries=False)
    assert "geometries" not in result.entries[0]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_multiple_locations_in_one_message_are_all_kept(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>45.0 -100.0</georss:point>"
        + "<georss:point>46.0 -101.0</georss:point>"
        + "<georss:line>45.0 -100.0 46.0 -101.0</georss:line>"
        + "<georss:polygon>0 0 1 0 1 1 0 0</georss:polygon>"
        + "</entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)},
        {"type": "Point", "coordinates": (-101.0, 46.0)},
        {
            "type": "LineString",
            "coordinates": ((-100.0, 45.0), (-101.0, 46.0)),
        },
        {
            "type": "Polygon",
            "coordinates": (
                ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.0, 0.0)),
            ),
        },
    ]
    # Output coordinates are always plain (longitude, latitude) float tuples.
    point = result.entries[0]["geometries"][0]["coordinates"]
    assert isinstance(point, tuple) and len(point) == 2
    assert all(isinstance(value, float) for value in point)


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_multiple_where_blocks_and_interleaved_order(parse, parser):
    # Regression: several georss:where blocks on one message used to
    # overwrite each other. They must all be retained, in document order,
    # interleaved with GeoRSS Simple geometries.
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>10.0 1.0</georss:point>"
        + "<georss:where>"
        + "<gml:Point><gml:pos>20.0 2.0</gml:pos></gml:Point>"
        + "</georss:where>"
        + "<georss:line>30.0 3.0 40.0 4.0</georss:line>"
        + "<georss:where>"
        + "<gml:LineString><gml:posList>50.0 5.0 60.0 6.0</gml:posList>"
        + "</gml:LineString></georss:where>"
        + "</entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    geometries = result.entries[0]["geometries"]
    assert [geometry["type"] for geometry in geometries] == [
        "Point",
        "Point",
        "LineString",
        "LineString",
    ]
    assert geometries[0]["coordinates"] == (1.0, 10.0)
    assert geometries[1]["coordinates"] == (2.0, 20.0)
    # The legacy where result still holds only the last geometry.
    assert result.entries[0]["where"]["type"] == "LineString"


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_gml_point_linestring_and_default_crs(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry><georss:where>"
        + "<gml:Point><gml:pos>36.9382 31.1732</gml:pos></gml:Point>"
        + "</georss:where><georss:where>"
        + "<gml:LineString><gml:posList>36.9 31.1 37.0 31.2</gml:posList>"
        + "</gml:LineString></georss:where></entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (31.1732, 36.9382)},
        {
            "type": "LineString",
            "coordinates": ((31.1, 36.9), (31.2, 37.0)),
        },
    ]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_polygon_keeps_exterior_and_all_interiors(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry><georss:where><gml:Polygon>"
        + "<gml:exterior><gml:LinearRing>"
        + "<gml:posList>0 0 0 10 10 10 10 0 0 0</gml:posList>"
        + "</gml:LinearRing></gml:exterior>"
        + "<gml:interior><gml:LinearRing>"
        + "<gml:posList>2 2 2 4 4 4 4 2 2 2</gml:posList>"
        + "</gml:LinearRing></gml:interior>"
        + "<gml:interior><gml:LinearRing>"
        + "<gml:posList>6 6 6 8 8 8 8 6 6 6</gml:posList>"
        + "</gml:LinearRing></gml:interior>"
        + "</gml:Polygon></georss:where></entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    polygon = result.entries[0]["geometries"][0]
    assert polygon["type"] == "Polygon"
    rings = polygon["coordinates"]
    assert len(rings) == 3
    assert rings[0][0] == (0.0, 0.0)
    assert rings[1][0] == (2.0, 2.0)
    assert rings[2][0] == (6.0, 6.0)
    for ring in rings:
        assert ring[0] == ring[-1]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_srs_name_urn_and_http_identifiers(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        # EPSG:4326 URN -- latitude first, must be swapped.
        + '<gml:Point srsName="urn:ogc:def:crs:EPSG::4326">'
        + "<gml:pos>20.0 10.0</gml:pos></gml:Point>"
        # EPSG:4326 HTTP identifier.
        + '<gml:Point srsName="http://www.opengis.net/def/crs/EPSG/0/4326">'
        + "<gml:pos>20.0 10.0</gml:pos></gml:Point>"
        # OGC CRS84 URN -- longitude first, passes through unchanged.
        + '<gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
        + "<gml:pos>10.0 20.0</gml:pos></gml:Point>"
        # OGC CRS84 HTTP identifier.
        + '<gml:Point srsName="http://www.opengis.net/def/crs/OGC/1.3/CRS84">'
        + "<gml:pos>10.0 20.0</gml:pos></gml:Point>"
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert warnings_ == []
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (10.0, 20.0)},
        {"type": "Point", "coordinates": (10.0, 20.0)},
        {"type": "Point", "coordinates": (10.0, 20.0)},
        {"type": "Point", "coordinates": (10.0, 20.0)},
    ]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_nested_srs_name_inheritance_and_override(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        # No srsName: defaults to EPSG:4326 (latitude first, swapped).
        + "<gml:Point><gml:pos>20.0 10.0</gml:pos></gml:Point>"
        # Explicit CRS84 overrides the default.
        + '<gml:Point srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
        + "<gml:pos>10.0 20.0</gml:pos></gml:Point>"
        # Blank srsName falls back to the default 4326 behavior.
        + '<gml:Point srsName=""><gml:pos>20.0 10.0</gml:pos></gml:Point>'
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert warnings_ == []
    assert [g["coordinates"] for g in result.entries[0]["geometries"]] == [
        (10.0, 20.0),
        (10.0, 20.0),
        (10.0, 20.0),
    ]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_unknown_crs_rejects_only_that_geometry(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + '<gml:Point srsName="EPSG:26913"><gml:pos>1 2</gml:pos></gml:Point>'
        + "<gml:Point><gml:pos>20.0 10.0</gml:pos></gml:Point>"
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (10.0, 20.0)}
    ]
    assert len(warnings_) == 1
    assert "#1" in warnings_[0] and "entry 0" in warnings_[0]
    assert "EPSG:26913" in warnings_[0]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_bad_geometries_are_skipped_but_later_ones_survive(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>95.0 200.0</georss:point>"  # out of range
        + "<georss:point>not numeric</georss:point>"  # non-finite/non-numeric
        + "<georss:line>10 20</georss:line>"  # too few points
        + "<georss:polygon>0 0 1 0 1 1</georss:polygon>"  # unclosed ring
        + "<georss:point>45.0 -100.0</georss:point>"  # valid
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)}
    ]
    assert len(warnings_) == 4
    # Geometry numbering is continuous across rejected geometries.
    for index, message in enumerate(warnings_, start=1):
        assert f"#{index}" in message
        assert "entry 0" in message


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_three_dimensional_geometries_are_rejected(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + '<gml:Point srsName="urn:ogc:def:crs:EPSG:6.6:4979" '
        + 'srsDimension="3"><gml:pos>1 2 3</gml:pos></gml:Point>'
        + '<gml:Point srsName="urn:ogc:def:crs:EPSG::4326">'
        + "<gml:pos>20 10</gml:pos></gml:Point>"
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert len(result.entries[0]["geometries"]) == 1
    assert result.entries[0]["geometries"][0] == {
        "type": "Point",
        "coordinates": (10.0, 20.0),
    }
    assert len(warnings_) == 1


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_geometries_never_leak_between_entries(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>bad</georss:point>"
        + "<georss:point>45.0 -100.0</georss:point>"
        + "</entry>"
        + "<entry>"
        + "<georss:point>10.0 20.0</georss:point>"
        + "</entry></feed>"
    )
    result, warnings_ = parse_with_warnings(xml, parser)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)}
    ]
    # The second entry's geometry is numbered from one again.
    assert result.entries[1]["geometries"] == [
        {"type": "Point", "coordinates": (20.0, 10.0)}
    ]
    assert len(warnings_) == 1
    assert "#1" in warnings_[0] and "entry 0" in warnings_[0]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_feed_level_and_entry_level_geometries_are_separate(parse, parser):
    xml = (
        ATOM_HEADER
        + "<georss:point>0.0 0.0</georss:point>"
        + "<entry><georss:point>1.0 1.0</georss:point></entry>"
        + "</feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    assert result.feed["geometries"] == [
        {"type": "Point", "coordinates": (0.0, 0.0)}
    ]
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (1.0, 1.0)}
    ]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_alias_namespace_prefixes_are_supported(parse, parser):
    xml = (
        '<rss version="2.0" '
        'xmlns:foo="http://www.georss.org/georss" '
        'xmlns:bar="http://www.opengis.net/gml">'
        + "<channel><item>"
        + "<foo:point>45.0 -100.0</foo:point>"
        + "<foo:where><bar:Point><bar:pos>20.0 10.0</bar:pos></bar:Point>"
        + "</foo:where>"
        + "</item></channel></rss>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)},
        {"type": "Point", "coordinates": (10.0, 20.0)},
    ]


@pytest.mark.parametrize("parser", ("strict", "loose"))
def test_bounding_box_is_not_collected(parse, parser):
    xml = (
        ATOM_HEADER
        + "<entry><georss:box>45 -100 46 -101</georss:box></entry></feed>"
    )
    result = parse(xml, parser=parser, collect_geometries=True)
    assert "geometries" not in result.entries[0]
    assert result.entries[0]["where"]["type"] == "Box"


def test_loose_parser_fallback_still_collects():
    # Malformed container XML forces the strict parser to fail and the
    # loose parser to take over; geometry collection must still work.
    xml = (
        ATOM_HEADER
        + "<entry>"
        + "<georss:point>45.0 -100.0</georss:point>"
        + "<georss:point>46.0 -101.0</georss:point>"
        + "<title>unclosed bold <b>x</title>"
        + "</entry></feed>"
    )
    result = feedparser.parse(xml, collect_geometries=True)
    assert result.bozo
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-100.0, 45.0)},
        {"type": "Point", "coordinates": (-101.0, 46.0)},
    ]


def test_json_feeds_are_unaffected():
    json_feed = (
        '{"version":"https://jsonfeed.org/version/1","title":"x",'
        '"items":[{"id":"1"}]}'
    )
    result = feedparser.parse(json_feed, collect_geometries=True)
    assert result.bozo is False
    assert "geometries" not in result.entries[0]
