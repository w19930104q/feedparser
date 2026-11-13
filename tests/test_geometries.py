"""Offline tests for the opt-in ``geometries`` mode (GeoRSS Simple + GML)."""

import io

import pytest

import feedparser
import feedparser.api

ATOM_HEADER = """<feed xmlns="http://www.w3.org/2005/Atom"
  xmlns:georss="http://www.georss.org/georss"
  xmlns:gml="http://www.opengis.net/gml">
"""

ATOM_FOOTER = "</feed>"


def parse(xml, **kwargs):
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return feedparser.parse(io.BytesIO(xml), **kwargs)


def atom(*body):
    return ATOM_HEADER + "".join(body) + ATOM_FOOTER


def entry(*body):
    return "<entry>" + "".join(body) + "</entry>"


def test_disabled_by_default():
    xml = atom(entry("<georss:point>45.0 -122.0</georss:point>"))
    result = parse(xml)
    assert "geometries" not in result.feed
    assert "geometries" not in result.entries[0]
    assert "geometries_diagnostics" not in result
    # The original ``where`` behavior is untouched.
    assert result.entries[0]["where"] == {
        "type": "Point",
        "coordinates": (-122.0, 45.0),
    }


def test_disabled_explicitly():
    xml = atom(entry("<georss:point>45.0 -122.0</georss:point>"))
    result = parse(xml, geometries=False)
    assert "geometries" not in result.feed
    assert "geometries" not in result.entries[0]
    assert "geometries_diagnostics" not in result


def test_enabled_without_geometries():
    result = parse(atom(entry("<title>x</title>")), geometries=True)
    assert result.feed["geometries"] == []
    assert result.entries[0]["geometries"] == []
    assert result["geometries_diagnostics"] == []


def test_global_default(monkeypatch):
    xml = atom(entry("<georss:point>45.0 -122.0</georss:point>"))
    monkeypatch.setattr(feedparser, "GEOMETRIES", 1)
    result = parse(xml)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-122.0, 45.0)}
    ]


def test_multiple_geometries_keep_document_order():
    # Multiple alert areas on one entry (and on the feed) are all kept,
    # in document order, with lat/lon swapped to lon/lat.
    xml = atom(
        "<georss:point>1.0 2.0</georss:point>",
        entry(
            "<georss:point>45.0 -122.0</georss:point>",
            "<georss:line>45.0 -122.0 46.0 -123.0</georss:line>",
            "<georss:polygon>"
            "45.0 -122.0 46.0 -122.0 46.0 -123.0 45.0 -122.0"
            "</georss:polygon>",
            "<georss:where><gml:Point><gml:pos>10.0 20.0</gml:pos></gml:Point>"
            "</georss:where>",
            "<georss:where><gml:LineString>"
            "<gml:posList>1.0 2.0 3.0 4.0</gml:posList>"
            "</gml:LineString></georss:where>",
        ),
    )
    result = parse(xml, geometries=True)
    assert result.feed["geometries"] == [{"type": "Point", "coordinates": (2.0, 1.0)}]
    geometries = result.entries[0]["geometries"]
    assert [g["type"] for g in geometries] == [
        "Point",
        "LineString",
        "Polygon",
        "Point",
        "LineString",
    ]
    assert geometries[0]["coordinates"] == (-122.0, 45.0)
    assert geometries[1]["coordinates"] == [(-122.0, 45.0), (-123.0, 46.0)]
    assert geometries[2]["coordinates"] == [
        [(-122.0, 45.0), (-122.0, 46.0), (-123.0, 46.0), (-122.0, 45.0)]
    ]
    assert geometries[3]["coordinates"] == (20.0, 10.0)
    assert geometries[4]["coordinates"] == [(2.0, 1.0), (4.0, 3.0)]
    assert result["geometries_diagnostics"] == []


def test_where_compatibility_when_enabled():
    xml = atom(
        entry(
            "<georss:point>45.0 -122.0</georss:point>",
            '<georss:where><gml:Point srsDimension="3">'
            "<gml:pos>42.0 -156.0 45.0</gml:pos>"
            "</gml:Point></georss:where>",
        )
    )
    enabled = parse(xml, geometries=True)
    disabled = parse(xml)
    assert enabled.entries[0]["where"] == disabled.entries[0]["where"]
    assert enabled.entries[0]["where"]["type"] == "Point"


def test_gml_polygon_with_interior_rings():
    # A polygon with holes keeps its exterior ring and all interior rings.
    xml = atom(
        entry(
            "<georss:where><gml:Polygon>",
            "<gml:exterior><gml:LinearRing><gml:posList>",
            "0.0 0.0 0.0 10.0 10.0 10.0 10.0 0.0 0.0 0.0",
            "</gml:posList></gml:LinearRing></gml:exterior>",
            "<gml:interior><gml:LinearRing><gml:posList>",
            "2.0 2.0 2.0 4.0 4.0 4.0 4.0 2.0 2.0 2.0",
            "</gml:posList></gml:LinearRing></gml:interior>",
            "<gml:interior><gml:LinearRing><gml:posList>",
            "6.0 6.0 6.0 8.0 8.0 8.0 8.0 6.0 6.0 6.0",
            "</gml:posList></gml:LinearRing></gml:interior>",
            "</gml:Polygon></georss:where>",
        )
    )
    result = parse(xml, geometries=True)
    (polygon,) = result.entries[0]["geometries"]
    assert polygon["type"] == "Polygon"
    exterior, hole1, hole2 = polygon["coordinates"]
    assert exterior == [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (0.0, 10.0),
        (0.0, 0.0),
    ]
    assert hole1 == [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0), (2.0, 2.0)]
    assert hole2 == [(6.0, 6.0), (8.0, 6.0), (8.0, 8.0), (6.0, 8.0), (6.0, 6.0)]
    assert result["geometries_diagnostics"] == []


def test_gml_point_and_linestring_with_multiple_pos():
    xml = atom(
        entry(
            "<georss:where><gml:LineString>",
            "<gml:pos>1.0 2.0</gml:pos><gml:pos>3.0 4.0</gml:pos>",
            "</gml:LineString></georss:where>",
        )
    )
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "LineString", "coordinates": [(2.0, 1.0), (4.0, 3.0)]}
    ]


def test_three_dimensional_coordinates_keep_altitude():
    xml = atom(
        entry(
            "<georss:where>",
            '<gml:Point srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="3">',
            "<gml:pos>42.3453 -156.2342 45.0</gml:pos>",
            "</gml:Point>",
            "</georss:where>",
            "<georss:where>",
            '<gml:LineString srsDimension="3">',
            "<gml:posList>1.0 2.0 100.0 3.0 4.0 200.0</gml:posList>",
            "</gml:LineString>",
            "</georss:where>",
        )
    )
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (-156.2342, 42.3453, 45.0)},
        {
            "type": "LineString",
            "coordinates": [(2.0, 1.0, 100.0), (4.0, 3.0, 200.0)],
        },
    ]


def test_srs_attributes_inherit_and_do_not_leak_to_siblings():
    # srsDimension on the first sibling must not affect the second one.
    xml = atom(
        entry(
            "<georss:where>",
            '<gml:Point srsDimension="3"><gml:pos>1.0 2.0 5.0</gml:pos></gml:Point>',
            "<gml:Point><gml:pos>3.0 4.0</gml:pos></gml:Point>",
            "</georss:where>",
        ),
        # srsName/srsDimension on a polygon are inherited by its rings.
        entry(
            "<georss:where>",
            '<gml:Polygon srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="3">',
            "<gml:exterior><gml:LinearRing><gml:posList>",
            "0.0 0.0 1.0 0.0 10.0 2.0 10.0 10.0 3.0 10.0 0.0 4.0 0.0 0.0 1.0",
            "</gml:posList></gml:LinearRing></gml:exterior>",
            "</gml:Polygon>",
            "</georss:where>",
        ),
        # Nothing leaks across entries: this point is two-dimensional again.
        entry(
            "<georss:where><gml:Point><gml:pos>5.0 6.0</gml:pos></gml:Point>"
            "</georss:where>"
        ),
    )
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (2.0, 1.0, 5.0)},
        {"type": "Point", "coordinates": (4.0, 3.0)},
    ]
    (polygon,) = result.entries[1]["geometries"]
    assert polygon["coordinates"][0][0] == (0.0, 0.0, 1.0)
    assert result.entries[2]["geometries"] == [
        {"type": "Point", "coordinates": (6.0, 5.0)}
    ]
    assert result["geometries_diagnostics"] == []


def test_srs_attribute_on_poslist_overrides_geometry_element():
    xml = atom(
        entry(
            "<georss:where>",
            '<gml:LineString srsDimension="3">',
            '<gml:posList srsDimension="2">1.0 2.0 3.0 4.0</gml:posList>',
            "</gml:LineString>",
            "</georss:where>",
        )
    )
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "LineString", "coordinates": [(2.0, 1.0), (4.0, 3.0)]}
    ]


def test_unsupported_srs_name_is_dropped_and_diagnosed():
    xml = atom(
        entry(
            "<georss:where>",
            '<gml:Point srsName="urn:ogc:def:crs:EPSG::3857">'
            "<gml:pos>1.0 2.0</gml:pos></gml:Point>",
            "<gml:Point><gml:pos>3.0 4.0</gml:pos></gml:Point>",
            "</georss:where>",
        )
    )
    result = parse(xml, geometries=True)
    # The bad geometry is dropped; its sibling is unaffected and is not
    # polluted by the unsupported srsName.
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (4.0, 3.0)}
    ]
    assert result["geometries_diagnostics"] == [
        {
            "entry": 0,
            "geometry": 0,
            "message": "unsupported srsName 'urn:ogc:def:crs:EPSG::3857'",
        }
    ]


@pytest.mark.parametrize(
    "snippet, message",
    (
        ("<georss:point>nan 1.0</georss:point>", "non-finite coordinate 'nan'"),
        ("<georss:point>1.0 inf</georss:point>", "non-finite coordinate 'inf'"),
        (
            "<georss:point>1.0</georss:point>",
            "coordinate count 1 is not a multiple of dimension 2",
        ),
        (
            "<georss:point>1.0 2.0 3.0 4.0</georss:point>",
            "point requires exactly 1 position, found 2",
        ),
        ("<georss:point>abc def</georss:point>", "invalid coordinate 'abc'"),
        (
            "<georss:line>1.0 2.0</georss:line>",
            "line requires at least 2 positions, found 1",
        ),
        (
            "<georss:polygon>0.0 0.0 1.0 0.0 1.0 1.0</georss:polygon>",
            "polygon ring requires at least 4 positions, found 3",
        ),
        (
            "<georss:polygon>0.0 0.0 1.0 0.0 1.0 1.0 2.0 2.0</georss:polygon>",
            "polygon ring is not closed",
        ),
    ),
)
def test_bad_georss_simple_geometries_are_dropped(snippet, message):
    xml = atom(entry(snippet, "<georss:point>10.0 20.0</georss:point>"))
    result = parse(xml, geometries=True)
    # The bad geometry is dropped as a whole; the valid one is kept.
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (20.0, 10.0)}
    ]
    assert result["geometries_diagnostics"] == [
        {"entry": 0, "geometry": 0, "message": message}
    ]


@pytest.mark.parametrize(
    "snippet, message",
    (
        (
            "<georss:where><gml:Point><gml:pos>1.0 nan</gml:pos></gml:Point>"
            "</georss:where>",
            "non-finite coordinate 'nan'",
        ),
        (
            "<georss:where><gml:Point><gml:pos>1.0</gml:pos></gml:Point>"
            "</georss:where>",
            "coordinate count 1 is not a multiple of dimension 2",
        ),
        (
            '<georss:where><gml:Point srsDimension="4">'
            "<gml:pos>1.0 2.0 3.0 4.0</gml:pos></gml:Point></georss:where>",
            "unsupported srsDimension '4'",
        ),
        (
            '<georss:where><gml:Point srsDimension="x">'
            "<gml:pos>1.0 2.0</gml:pos></gml:Point></georss:where>",
            "invalid srsDimension 'x'",
        ),
        (
            "<georss:where><gml:LineString>"
            "<gml:posList>1.0 2.0</gml:posList>"
            "</gml:LineString></georss:where>",
            "line requires at least 2 positions, found 1",
        ),
        (
            "<georss:where><gml:Polygon></gml:Polygon></georss:where>",
            "polygon has no exterior ring",
        ),
        (
            # An invalid interior ring invalidates the whole polygon.
            "<georss:where><gml:Polygon>"
            "<gml:exterior><gml:LinearRing><gml:posList>"
            "0.0 0.0 0.0 10.0 10.0 10.0 10.0 0.0 0.0 0.0"
            "</gml:posList></gml:LinearRing></gml:exterior>"
            "<gml:interior><gml:LinearRing><gml:posList>"
            "2.0 2.0 4.0 4.0"
            "</gml:posList></gml:LinearRing></gml:interior>"
            "</gml:Polygon></georss:where>",
            "polygon ring requires at least 4 positions, found 2",
        ),
        (
            # An unclosed exterior ring invalidates the whole polygon.
            "<georss:where><gml:Polygon>"
            "<gml:exterior><gml:LinearRing><gml:posList>"
            "0.0 0.0 0.0 10.0 10.0 10.0 10.0 0.0"
            "</gml:posList></gml:LinearRing></gml:exterior>"
            "</gml:Polygon></georss:where>",
            "polygon ring is not closed",
        ),
    ),
)
def test_bad_gml_geometries_are_dropped(snippet, message):
    xml = atom(entry(snippet, "<georss:point>10.0 20.0</georss:point>"))
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (20.0, 10.0)}
    ]
    assert result["geometries_diagnostics"] == [
        {"entry": 0, "geometry": 0, "message": message}
    ]


def test_diagnostics_identify_entry_and_geometry_ordinal():
    xml = atom(
        "<georss:point>0.0 0.0</georss:point>",
        entry("<georss:point>1.0 2.0</georss:point>"),
        entry(
            "<georss:point>1.0 2.0</georss:point>",
            "<georss:point>bad coordinates</georss:point>",
            "<georss:line>1.0 2.0 3.0 4.0</georss:line>",
        ),
    )
    result = parse(xml, geometries=True)
    assert result.feed["geometries"] == [{"type": "Point", "coordinates": (0.0, 0.0)}]
    assert len(result.entries[0]["geometries"]) == 1
    # Entry 1: geometries 0 and 2 are valid, geometry 1 is dropped.
    assert [g["type"] for g in result.entries[1]["geometries"]] == [
        "Point",
        "LineString",
    ]
    assert result["geometries_diagnostics"] == [
        {"entry": 1, "geometry": 1, "message": "invalid coordinate 'bad'"}
    ]


def test_feed_level_bad_geometry_has_no_entry_index():
    xml = atom(
        "<georss:point>1.0</georss:point>",
        entry("<georss:point>1.0 2.0</georss:point>"),
    )
    result = parse(xml, geometries=True)
    assert result.feed["geometries"] == []
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (2.0, 1.0)}
    ]
    assert result["geometries_diagnostics"] == [
        {
            "entry": None,
            "geometry": 0,
            "message": "coordinate count 1 is not a multiple of dimension 2",
        }
    ]


def test_georss_box_is_not_collected():
    # georss:box remains available through ``where`` only.
    xml = atom(entry("<georss:box>1.0 2.0 3.0 4.0</georss:box>"))
    result = parse(xml, geometries=True)
    assert result.entries[0]["geometries"] == []
    assert result.entries[0]["where"]["type"] == "Box"
    assert result["geometries_diagnostics"] == []


def test_rss20_feed_and_item_geometries():
    xml = """
    <rss version="2.0" xmlns:georss="http://www.georss.org/georss">
      <channel>
        <georss:point>1.0 2.0</georss:point>
        <item><georss:point>3.0 4.0</georss:point></item>
        <item><georss:point>5.0 6.0</georss:point></item>
      </channel>
    </rss>
    """
    result = parse(xml, geometries=True)
    assert result.feed["geometries"] == [{"type": "Point", "coordinates": (2.0, 1.0)}]
    assert result.entries[0]["geometries"] == [
        {"type": "Point", "coordinates": (4.0, 3.0)}
    ]
    assert result.entries[1]["geometries"] == [
        {"type": "Point", "coordinates": (6.0, 5.0)}
    ]


CONSISTENCY_FEEDS = [
    atom(
        "<georss:point>1.0 2.0</georss:point>",
        entry(
            "<georss:point>45.0 -122.0</georss:point>",
            "<georss:line>45.0 -122.0 46.0 -123.0</georss:line>",
            "<georss:polygon>"
            "45.0 -122.0 46.0 -122.0 46.0 -123.0 45.0 -122.0"
            "</georss:polygon>",
        ),
    ),
    atom(
        entry(
            "<georss:where><gml:Polygon>",
            "<gml:exterior><gml:LinearRing><gml:posList>",
            "0.0 0.0 0.0 10.0 10.0 10.0 10.0 0.0 0.0 0.0",
            "</gml:posList></gml:LinearRing></gml:exterior>",
            "<gml:interior><gml:LinearRing><gml:posList>",
            "2.0 2.0 2.0 4.0 4.0 4.0 4.0 2.0 2.0 2.0",
            "</gml:posList></gml:LinearRing></gml:interior>",
            "</gml:Polygon></georss:where>",
        )
    ),
    atom(
        entry(
            "<georss:where>",
            '<gml:Point srsName="urn:ogc:def:crs:EPSG::4326" srsDimension="3">',
            "<gml:pos>42.3453 -156.2342 45.0</gml:pos>",
            "</gml:Point>",
            '<gml:Point srsDimension="3"><gml:pos>1.0 2.0 5.0</gml:pos></gml:Point>',
            "<gml:Point><gml:pos>3.0 4.0</gml:pos></gml:Point>",
            "</georss:where>",
        ),
        entry(
            "<georss:point>nan 1.0</georss:point>",
            '<georss:where><gml:Point srsName="urn:ogc:def:crs:EPSG::3857">'
            "<gml:pos>1.0 2.0</gml:pos></gml:Point></georss:where>",
            "<georss:point>10.0 20.0</georss:point>",
        ),
    ),
]


@pytest.mark.parametrize("xml", CONSISTENCY_FEEDS)
def test_strict_and_loose_parsers_agree(xml, monkeypatch):
    strict = parse(xml, geometries=True)
    monkeypatch.setattr(feedparser.api, "_XML_AVAILABLE", False)
    loose = parse(xml, geometries=True)
    assert strict.feed["geometries"] == loose.feed["geometries"]
    assert [e["geometries"] for e in strict.entries] == [
        e["geometries"] for e in loose.entries
    ]
    assert strict["geometries_diagnostics"] == loose["geometries_diagnostics"]


@pytest.mark.parametrize("xml", CONSISTENCY_FEEDS)
def test_loose_parser(xml, use_loose_parser):
    # The loose parser alone must produce valid results too.
    result = parse(xml, geometries=True)
    assert result["bozo"] is False
    assert "geometries" in result.feed
