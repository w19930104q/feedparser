# Support for the GeoRSS format
# Copyright 2010-2025 Kurt McKee <contactme@kurtmckee.org>
# Copyright 2002-2008 Mark Pilgrim
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 'AS IS'
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import math
import warnings

from ..exceptions import GeometryWarning
from ..util import FeedParserDict

# The coordinate reference systems accepted by the ``geometries`` result.
# Only two-dimensional longitude/latitude CRSs are supported, so no
# projection or datum conversion is ever performed.
#
# * EPSG:4326 -- coordinate tuples in the source document are ordered
#   latitude first, longitude second, and are swapped on output.
# * OGC CRS84 -- coordinate tuples are already ordered
#   longitude first, latitude second, and are emitted unchanged.
#
# Both CRSs may be identified by their standard URN or HTTP identifiers.
_EPSG_4326_URNS = {
    "urn:ogc:def:crs:epsg::4326",
    "urn:ogc:def:crs:epsg:6.6:4326",
    "urn:ogc:def:crs:epsg:6.11:4326",
    "urn:ogc:def:crs:epsg:6.18:4326",
    "http://www.opengis.net/def/crs/epsg/0/4326",
    "http://www.opengis.net/gml/srs/epsg.xml#4326",
}
_OGC_CRS84_URNS = {
    "urn:ogc:def:crs:ogc::crs84",
    "urn:ogc:def:crs:ogc:1.3:crs84",
    "http://www.opengis.net/def/crs/ogc/1.3/crs84",
}


class Namespace:
    supported_namespaces = {
        "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo",
        "http://www.georss.org/georss": "georss",
        "http://www.opengis.net/gml": "gml",
    }

    def __init__(self):
        self.ingeometry = 0
        # State for the opt-in ``geometries`` result. ``collect_geometries``
        # is set by the API layer and defaults to a falsy value so that the
        # legacy ``where`` behavior is completely unchanged unless requested.
        self.collect_geometries = False
        # A stack of in-progress geometry frames, independent of the legacy
        # ``geometry``/``pos`` element stack so the two paths never interact.
        self._geometry_frames = []
        # Per-context geometry counters, keyed by the context dict itself so
        # that feed-level and entry-level geometries are counted separately
        # and counters never leak between entries.
        self._geometry_counts = {}
        super().__init__()

    # ------------------------------------------------------------------
    # Legacy ``where`` handling. This path is preserved unchanged; the
    # ``geometries`` collector below runs alongside it without sharing
    # mutable state.
    # ------------------------------------------------------------------

    def _start_georssgeom(self, attrs_d):
        self.push("geometry", 0)
        context = self._get_context()
        context["where"] = FeedParserDict()

    _start_georss_point = _start_georssgeom
    _start_georss_line = _start_georssgeom
    _start_georss_polygon = _start_georssgeom
    _start_georss_box = _start_georssgeom

    def _save_where(self, geometry):
        context = self._get_context()
        context["where"].update(geometry)

    def _end_georss_point(self):
        text = self.pop("geometry")
        geometry = _parse_georss_point(text)
        if geometry:
            self._save_where(geometry)
        self._collect_simple_geometry("Point", text)

    def _end_georss_line(self):
        text = self.pop("geometry")
        geometry = _parse_georss_line(text)
        if geometry:
            self._save_where(geometry)
        self._collect_simple_geometry("LineString", text)

    def _end_georss_polygon(self):
        text = self.pop("geometry")
        geometry = _parse_georss_polygon(text)
        if geometry:
            self._save_where(geometry)
        self._collect_simple_geometry("Polygon", text)

    def _end_georss_box(self):
        geometry = _parse_georss_box(self.pop("geometry"))
        if geometry:
            self._save_where(geometry)

    def _start_where(self, attrs_d):
        self.push("where", 0)
        context = self._get_context()
        context["where"] = FeedParserDict()

    _start_georss_where = _start_where

    def _parse_srs_attrs(self, attrs_d):
        srs_name = attrs_d.get("srsname")
        try:
            srs_dimension = int(attrs_d.get("srsdimension", "2"))
        except ValueError:
            srs_dimension = 2
        context = self._get_context()
        if "where" not in context:
            context["where"] = {}
        context["where"]["srsName"] = srs_name
        context["where"]["srsDimension"] = srs_dimension

    def _start_gml_point(self, attrs_d):
        self._parse_srs_attrs(attrs_d)
        self.ingeometry = 1
        self.push("geometry", 0)
        self._start_collected_gml_geometry("Point", attrs_d)

    def _start_gml_linestring(self, attrs_d):
        self._parse_srs_attrs(attrs_d)
        self.ingeometry = "linestring"
        self.push("geometry", 0)
        self._start_collected_gml_geometry("LineString", attrs_d)

    def _start_gml_polygon(self, attrs_d):
        self._parse_srs_attrs(attrs_d)
        self.push("geometry", 0)
        self._start_collected_gml_geometry("Polygon", attrs_d)

    def _start_gml_exterior(self, attrs_d):
        self.push("geometry", 0)
        self._collect_start_ring("exterior")

    def _start_gml_interior(self, attrs_d):
        self._collect_start_ring("interior")

    def _start_gml_linearring(self, attrs_d):
        self.ingeometry = "polygon"
        self.push("geometry", 0)

    def _start_gml_pos(self, attrs_d):
        self.push("pos", 0)

    def _end_gml_pos(self):
        this = self.pop("pos")
        swap = self._legacy_swap()
        srs_dimension = self._get_context()["where"].get("srsDimension", 2)
        geometry = _parse_georss_point(this, swap=swap, dims=srs_dimension)
        if geometry:
            self._save_where(geometry)
        self._collect_gml_coordinate_text(this)

    def _start_gml_poslist(self, attrs_d):
        self.push("pos", 0)

    def _end_gml_poslist(self):
        this = self.pop("pos")
        swap = self._legacy_swap()
        srs_dimension = self._get_context()["where"].get("srsDimension", 2)
        geometry = _parse_poslist(this, self.ingeometry, swap=swap, dims=srs_dimension)
        if geometry:
            self._save_where(geometry)
        self._collect_gml_coordinate_text(this)

    def _legacy_swap(self):
        # Determine the legacy ``where`` axis order. Only bare ``EPSG:####``
        # identifiers are understood historically; anything else (including
        # URN/HTTP identifiers) defaults to latitude-first swapping.
        srs_name = self._get_context()["where"].get("srsName")
        if srs_name and "EPSG" in srs_name:
            try:
                epsg = int(srs_name.split(":")[-1])
            except ValueError:
                return True
            return bool(epsg in _geogCS)
        return True

    def _end_geom(self):
        self.ingeometry = 0
        self.pop("geometry")

    def _end_gml_point(self):
        self._end_geom()
        self._collect_end_gml_geometry()

    def _end_gml_linestring(self):
        self._end_geom()
        self._collect_end_gml_geometry()

    def _end_gml_linearring(self):
        self._end_geom()
        self._collect_end_ring()

    def _end_gml_exterior(self):
        self._end_geom()

    def _end_gml_interior(self):
        self._collect_end_ring_container()

    def _end_gml_polygon(self):
        self._end_geom()
        self._collect_end_gml_geometry()

    def _end_where(self):
        self.pop("where")

    _end_georss_where = _end_where

    # ------------------------------------------------------------------
    # Opt-in ``geometries`` collector.
    #
    # Every GeoRSS Simple and GML geometry encountered on a feed or entry
    # is validated independently and, if valid, appended to that context's
    # ``geometries`` list in document order. A rejected geometry is dropped
    # (with a GeometryWarning identifying the entry and geometry index) and
    # can never affect neighboring geometries or other entries.
    # ------------------------------------------------------------------

    def _start_item(self, attrs_d):
        # Entries start with a fresh per-entry geometry counter. The base
        # namespace implementation creates the entry context dict.
        super()._start_item(attrs_d)
        context = self._get_context()
        self._geometry_counts.pop(context, None)
        # Defensive: a malformed feed may leave geometry frames open when
        # an entry closes early. Drop any stray frames so geometry state can
        # never leak from one entry into the next one.
        self._geometry_frames = []

    _start_entry = _start_item

    def _geometry_index(self, context):
        index = self._geometry_counts.get(context, 0) + 1
        self._geometry_counts[context] = index
        return index

    def _reject_geometry(self, frame, reason):
        context = self._get_context()
        index = frame["index"]
        warnings.warn(
            "Rejected GeoRSS geometry #{} on {}: {}".format(
                index, self._geometry_context_label(context), reason
            ),
            GeometryWarning,
            stacklevel=2,
        )

    def _geometry_context_label(self, context):
        if self.inentry:
            # Covers entry bodies as well as entry-level image, text input
            # and source contexts, all of which belong to the current entry.
            return "entry {}".format(len(self.entries) - 1)
        return "the feed"

    def _append_geometry(self, frame, geometry):
        context = self._get_context()
        context.setdefault("geometries", []).append(geometry)

    # -- GeoRSS Simple geometries --------------------------------------

    def _collect_simple_geometry(self, geom_type, text):
        """Validate a GeoRSS Simple geometry for the geometries result.

        The raw coordinate text is validated independently of the legacy
        ``where`` parsers: the legacy parsers are intentionally permissive
        (they accept 3D points, out of range values, unclosed rings, ...),
        whereas the geometries result only accepts finite, in-range,
        two-dimensional coordinates in closed polygon rings.
        """
        if not self.collect_geometries:
            return
        context = self._get_context()
        frame = {"index": self._geometry_index(context), "type": geom_type}
        # GeoRSS Simple coordinates are always WGS84 latitude first, so the
        # values must be swapped into (longitude, latitude) order.
        if geom_type == "Point":
            parsed = _build_point(text, swap=True)
        elif geom_type == "LineString":
            parsed = _build_line(text, swap=True)
        else:  # Polygon
            ring = _parse_ring_text(text, None)
            if ring is None:
                parsed = None
            else:
                parsed = {"type": "Polygon", "coordinates": (ring,)}
        if parsed is None:
            self._reject_geometry(
                frame, "invalid GeoRSS Simple {}".format(geom_type)
            )
            return
        self._append_geometry(frame, parsed)

    # -- GML geometries -------------------------------------------------

    def _start_collected_gml_geometry(self, geom_type, attrs_d):
        if not self.collect_geometries:
            return
        context = self._get_context()
        # Resolve the srsName before pushing this geometry's frame, so an
        # explicit attribute on the geometry cannot be shadowed by itself
        # through ancestor inheritance.
        srs_name = _resolve_srs_name(
            attrs_d.get("srsname"),
            self._inherited_srs_name(),
        )
        frame = {
            "index": self._geometry_index(context),
            "type": geom_type,
            "srs_name": srs_name,
            "rings": [],
            "ring_role": None,
            "has_coordinates": False,
        }
        self._geometry_frames.append(frame)

    def _inherited_srs_name(self):
        # GML allows an srsName on an enclosing geometry (or any ancestor)
        # to be inherited by nested geometry elements.
        for frame in reversed(self._geometry_frames[:-1]):
            if frame["srs_name"] is not None:
                return frame["srs_name"]
        return None

    def _collect_start_ring(self, role):
        if not self.collect_geometries or not self._geometry_frames:
            return
        self._geometry_frames[-1]["ring_role"] = role

    def _collect_end_ring_container(self):
        if not self.collect_geometries or not self._geometry_frames:
            return
        # The interior/exterior element has closed; reset the active role
        # so stray coordinate text cannot attach to the finished ring.
        self._geometry_frames[-1]["ring_role"] = None

    def _collect_gml_coordinate_text(self, text):
        if not self.collect_geometries or not self._geometry_frames:
            return
        frame = self._geometry_frames[-1]
        if frame["has_coordinates"]:
            # A geometry carries exactly one coordinate encoding; ignore
            # any additional pos/posList elements instead of merging them.
            return
        frame["has_coordinates"] = True
        frame["raw_text"] = text

    def _collect_end_ring(self):
        if not self.collect_geometries or not self._geometry_frames:
            return
        frame = self._geometry_frames[-1]
        if frame["type"] != "Polygon":
            return
        text = frame.pop("raw_text", "")
        role = frame["ring_role"] or "exterior"
        ring = _parse_ring_text(text, frame["srs_name"])
        frame["rings"].append((role, ring))
        frame["ring_role"] = None
        frame["has_coordinates"] = False

    def _collect_end_gml_geometry(self):
        if not self.collect_geometries or not self._geometry_frames:
            return
        frame = self._geometry_frames.pop()
        srs_name = frame["srs_name"]
        axis = _crs_axis_order(srs_name)
        if axis is None:
            self._reject_geometry(
                frame, "unknown or unsupported srsName {!r}".format(srs_name)
            )
            return
        swap = axis == "latlon"
        geom_type = frame["type"]

        if geom_type == "Polygon":
            geometry = self._build_collected_polygon(frame)
        else:
            text = frame.get("raw_text", "")
            if geom_type == "Point":
                geometry = _build_point(text, swap=swap)
            else:  # LineString
                geometry = _build_line(text, swap=swap)
        if geometry is None:
            self._reject_geometry(frame, "invalid GML {}".format(geom_type))
            return
        self._append_geometry(frame, geometry)

    def _build_collected_polygon(self, frame):
        rings = frame["rings"]
        exterior = [ring for role, ring in rings if role == "exterior"]
        if len(exterior) != 1 or exterior[0] is None:
            return None
        interiors = [ring for role, ring in rings if role == "interior"]
        if any(ring is None for ring in interiors):
            return None
        coordinates = [exterior[0]] + interiors
        return {"type": "Polygon", "coordinates": tuple(coordinates)}


# GeoRSS geometry parsers. Each return a dict with 'type' and 'coordinates'
# items, or None in the case of a parsing error.


def _parse_poslist(value, geom_type, swap=True, dims=2):
    if geom_type == "linestring":
        return _parse_georss_line(value, swap, dims)
    if geom_type == "polygon":
        ring = _parse_georss_line(value, swap, dims)
        return {"type": "Polygon", "coordinates": (ring["coordinates"],)}
    return None


def _gen_georss_coords(value, swap=True, dims=2):
    # A generator of (lon, lat) pairs from a string of encoded GeoRSS
    # coordinates. Converts to floats and swaps order.
    latlons = (float(ll) for ll in value.replace(",", " ").split())
    while True:
        try:
            t = [next(latlons), next(latlons)][:: swap and -1 or 1]
            if dims == 3:
                t.append(next(latlons))
            yield tuple(t)
        except StopIteration:
            return


def _parse_georss_point(value, swap=True, dims=2):
    # A point contains a single latitude-longitude pair, separated by
    # whitespace. We'll also handle comma separators.
    try:
        coords = list(_gen_georss_coords(value, swap, dims))
        return {"type": "Point", "coordinates": coords[0]}
    except (IndexError, ValueError):
        return None


def _parse_georss_line(value, swap=True, dims=2):
    # A line contains a space separated list of latitude-longitude pairs in
    # WGS84 coordinate reference system, with each pair separated by
    # whitespace. There must be at least two pairs.
    try:
        coords = list(_gen_georss_coords(value, swap, dims))
        return {"type": "LineString", "coordinates": coords}
    except (IndexError, ValueError):
        return None


def _parse_georss_polygon(value, swap=True, dims=2):
    # A polygon contains a space separated list of latitude-longitude pairs,
    # with each pair separated by whitespace. There must be at least four
    # pairs, with the last being identical to the first (so a polygon has a
    # minimum of three actual points).
    try:
        ring = list(_gen_georss_coords(value, swap, dims))
    except (IndexError, ValueError):
        return None
    if len(ring) < 4:
        return None
    return {"type": "Polygon", "coordinates": (ring,)}


def _parse_georss_box(value, swap=True, dims=2):
    # A bounding box is a rectangular region, often used to define the extents
    # of a map or a rough area of interest. A box contains two space separate
    # latitude-longitude pairs, with each pair separated by whitespace. The
    # first pair is the lower corner, the second is the upper corner.
    try:
        coords = list(_gen_georss_coords(value, swap, dims))
        return {"type": "Box", "coordinates": tuple(coords)}
    except (IndexError, ValueError):
        return None


# ----------------------------------------------------------------------
# Strict validators used exclusively by the opt-in ``geometries`` result.
#
# Every output coordinate is a finite two-dimensional (longitude, latitude)
# tuple of Python floats. No projection or datum conversion is performed:
# EPSG:4326 input is latitude-first and gets swapped, OGC CRS84 input is
# longitude-first and passes through unchanged. Any geometry that violates
# these rules is rejected in full (the validator returns ``None``) so that
# a single bad geometry can never contaminate another one.
# ----------------------------------------------------------------------


def _resolve_srs_name(srs_name, inherited):
    """Resolve an element's srsName, applying GML inheritance.

    A missing or blank attribute inherits the nearest ancestor srsName;
    an explicitly present attribute (even if unknown) overrides it.
    """
    if srs_name is None or not str(srs_name).strip():
        return inherited
    return str(srs_name).strip()


def _crs_axis_order(srs_name):
    """Return ``'latlon'`` (EPSG:4326) or ``'lonlat'`` (OGC CRS84).

    Returns ``None`` for unknown or unsupported coordinate reference
    systems, including projected and three-dimensional CRSs.
    """
    if srs_name is None:
        # GeoRSS Simple and GML without an srsName default to WGS84
        # latitude/longitude, i.e. EPSG:4326 axis order.
        return "latlon"
    normalized = srs_name.strip().lower()
    if normalized in _EPSG_4326_URNS or normalized == "epsg:4326":
        return "latlon"
    if normalized in _OGC_CRS84_URNS:
        return "lonlat"
    return None


def _tokenize_coordinates(text):
    """Split coordinate text into floats, rejecting non-finite tokens.

    Returns a flat list of floats, or ``None`` if any token is missing,
    non-numeric, or not a finite number.
    """
    try:
        values = [float(token) for token in text.replace(",", " ").split()]
    except (ValueError, TypeError):
        return None
    if any(not math.isfinite(value) for value in values):
        return None
    return values


def _pair_up(values, swap):
    """Group a flat coordinate list into (longitude, latitude) 2-tuples.

    Rejects incomplete tuples (a trailing single value), non-finite values,
    and out-of-range longitude/latitude components.
    """
    if values is None or len(values) < 2 or len(values) % 2:
        return None
    points = []
    for i in range(0, len(values), 2):
        first, second = values[i], values[i + 1]
        if swap:
            lon, lat = second, first
        else:
            lon, lat = first, second
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return None
        points.append((lon, lat))
    return points


def _build_point(text, swap):
    points = _pair_up(_tokenize_coordinates(text), swap)
    if points is None or len(points) != 1:
        return None
    return {"type": "Point", "coordinates": points[0]}


def _build_line(text, swap):
    points = _pair_up(_tokenize_coordinates(text), swap)
    if points is None or len(points) < 2:
        return None
    return {"type": "LineString", "coordinates": tuple(points)}


def _parse_ring_text(text, srs_name):
    """Parse and validate one polygon ring's coordinate text."""
    axis = _crs_axis_order(srs_name)
    if axis is None:
        return None
    points = _pair_up(_tokenize_coordinates(text), swap=(axis == "latlon"))
    if points is None or not _is_closed_ring(points):
        return None
    return tuple(points)


def _is_closed_ring(points):
    # A ring needs at least four positions (three distinct points plus a
    # closing position identical to the first) and must be explicitly
    # closed; open rings are rejected rather than closed implicitly.
    return len(points) >= 4 and points[0] == points[-1]


# The list of EPSG codes for geographic (latitude/longitude) coordinate
# systems to support decoding of GeoRSS GML profiles.
_geogCS = [
    3819,
    3821,
    3824,
    3889,
    3906,
    4001,
    4002,
    4003,
    4004,
    4005,
    4006,
    4007,
    4008,
    4009,
    4010,
    4011,
    4012,
    4013,
    4014,
    4015,
    4016,
    4018,
    4019,
    4020,
    4021,
    4022,
    4023,
    4024,
    4025,
    4027,
    4028,
    4029,
    4030,
    4031,
    4032,
    4033,
    4034,
    4035,
    4036,
    4041,
    4042,
    4043,
    4044,
    4045,
    4046,
    4047,
    4052,
    4053,
    4054,
    4055,
    4075,
    4081,
    4120,
    4121,
    4122,
    4123,
    4124,
    4125,
    4126,
    4127,
    4128,
    4129,
    4130,
    4131,
    4132,
    4133,
    4134,
    4135,
    4136,
    4137,
    4138,
    4139,
    4140,
    4141,
    4142,
    4143,
    4144,
    4145,
    4146,
    4147,
    4148,
    4149,
    4150,
    4151,
    4152,
    4153,
    4154,
    4155,
    4156,
    4157,
    4158,
    4159,
    4160,
    4161,
    4162,
    4163,
    4164,
    4165,
    4166,
    4167,
    4168,
    4169,
    4170,
    4171,
    4172,
    4173,
    4174,
    4175,
    4176,
    4178,
    4179,
    4180,
    4181,
    4182,
    4183,
    4184,
    4185,
    4188,
    4189,
    4190,
    4191,
    4192,
    4193,
    4194,
    4195,
    4196,
    4197,
    4198,
    4199,
    4200,
    4201,
    4202,
    4203,
    4204,
    4205,
    4206,
    4207,
    4208,
    4209,
    4210,
    4211,
    4212,
    4213,
    4214,
    4215,
    4216,
    4218,
    4219,
    4220,
    4221,
    4222,
    4223,
    4224,
    4225,
    4226,
    4227,
    4228,
    4229,
    4230,
    4231,
    4232,
    4233,
    4234,
    4235,
    4236,
    4237,
    4238,
    4239,
    4240,
    4241,
    4242,
    4243,
    4244,
    4245,
    4246,
    4247,
    4248,
    4249,
    4250,
    4251,
    4252,
    4253,
    4254,
    4255,
    4256,
    4257,
    4258,
    4259,
    4260,
    4261,
    4262,
    4263,
    4264,
    4265,
    4266,
    4267,
    4268,
    4269,
    4270,
    4271,
    4272,
    4273,
    4274,
    4275,
    4276,
    4277,
    4278,
    4279,
    4280,
    4281,
    4282,
    4283,
    4284,
    4285,
    4286,
    4287,
    4288,
    4289,
    4291,
    4292,
    4293,
    4294,
    4295,
    4296,
    4297,
    4298,
    4299,
    4300,
    4301,
    4302,
    4303,
    4304,
    4306,
    4307,
    4308,
    4309,
    4310,
    4311,
    4312,
    4313,
    4314,
    4315,
    4316,
    4317,
    4318,
    4319,
    4322,
    4324,
    4326,
    4463,
    4470,
    4475,
    4483,
    4490,
    4555,
    4558,
    4600,
    4601,
    4602,
    4603,
    4604,
    4605,
    4606,
    4607,
    4608,
    4609,
    4610,
    4611,
    4612,
    4613,
    4614,
    4615,
    4616,
    4617,
    4618,
    4619,
    4620,
    4621,
    4622,
    4623,
    4624,
    4625,
    4626,
    4627,
    4628,
    4629,
    4630,
    4631,
    4632,
    4633,
    4634,
    4635,
    4636,
    4637,
    4638,
    4639,
    4640,
    4641,
    4642,
    4643,
    4644,
    4645,
    4646,
    4657,
    4658,
    4659,
    4660,
    4661,
    4662,
    4663,
    4664,
    4665,
    4666,
    4667,
    4668,
    4669,
    4670,
    4671,
    4672,
    4673,
    4674,
    4675,
    4676,
    4677,
    4678,
    4679,
    4680,
    4681,
    4682,
    4683,
    4684,
    4685,
    4686,
    4687,
    4688,
    4689,
    4690,
    4691,
    4692,
    4693,
    4694,
    4695,
    4696,
    4697,
    4698,
    4699,
    4700,
    4701,
    4702,
    4703,
    4704,
    4705,
    4706,
    4707,
    4708,
    4709,
    4710,
    4711,
    4712,
    4713,
    4714,
    4715,
    4716,
    4717,
    4718,
    4719,
    4720,
    4721,
    4722,
    4723,
    4724,
    4725,
    4726,
    4727,
    4728,
    4729,
    4730,
    4731,
    4732,
    4733,
    4734,
    4735,
    4736,
    4737,
    4738,
    4739,
    4740,
    4741,
    4742,
    4743,
    4744,
    4745,
    4746,
    4747,
    4748,
    4749,
    4750,
    4751,
    4752,
    4753,
    4754,
    4755,
    4756,
    4757,
    4758,
    4759,
    4760,
    4761,
    4762,
    4763,
    4764,
    4765,
    4801,
    4802,
    4803,
    4804,
    4805,
    4806,
    4807,
    4808,
    4809,
    4810,
    4811,
    4813,
    4814,
    4815,
    4816,
    4817,
    4818,
    4819,
    4820,
    4821,
    4823,
    4824,
    4901,
    4902,
    4903,
    4904,
    4979,
]
