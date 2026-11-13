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

from ..util import FeedParserDict

# The only CRS identifier supported by the opt-in ``geometries`` mode,
# besides an absent ``srsName`` (which means WGS 84). Compared in lowercase.
_SUPPORTED_SRS_NAME = "urn:ogc:def:crs:epsg::4326"


class _GeometryError(ValueError):
    """Raised when a geometry cannot be built from the given coordinates."""


class Namespace:
    supported_namespaces = {
        "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo",
        "http://www.georss.org/georss": "georss",
        "http://www.opengis.net/gml": "gml",
    }

    def __init__(self):
        self.ingeometry = 0
        # State for the opt-in ``geometries`` mode. ``geometries`` is toggled
        # by feedparser.parse(); the rest tracks GML element scoping and
        # per-context geometry ordinals while parsing.
        self.geometries = False
        self.geometries_diagnostics = []
        self._geom_ordinals = {}
        self._geom_stack = []
        super().__init__()

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
        if self.geometries:
            self._collect_simple_geometry("point", text)

    def _end_georss_line(self):
        text = self.pop("geometry")
        geometry = _parse_georss_line(text)
        if geometry:
            self._save_where(geometry)
        if self.geometries:
            self._collect_simple_geometry("linestring", text)

    def _end_georss_polygon(self):
        text = self.pop("geometry")
        geometry = _parse_georss_polygon(text)
        if geometry:
            self._save_where(geometry)
        if self.geometries:
            self._collect_simple_geometry("polygon", text)

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
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("point", attrs_d))

    def _start_gml_linestring(self, attrs_d):
        self._parse_srs_attrs(attrs_d)
        self.ingeometry = "linestring"
        self.push("geometry", 0)
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("linestring", attrs_d))

    def _start_gml_polygon(self, attrs_d):
        self._parse_srs_attrs(attrs_d)
        self.push("geometry", 0)
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("polygon", attrs_d))

    def _start_gml_exterior(self, attrs_d):
        self.push("geometry", 0)
        if self.geometries:
            self._geom_stack.append({"kind": "exterior"})

    def _start_gml_interior(self, attrs_d):
        if not self.geometries:
            # Replicate the historical fallback for elements without
            # a handler so that nothing changes when the opt-in
            # ``geometries`` mode is disabled.
            if not attrs_d:
                return self.push("gml_interior", 1)
            self._get_context()["gml_interior"] = attrs_d
            return
        self._geom_stack.append({"kind": "interior"})

    def _start_gml_linearring(self, attrs_d):
        self.ingeometry = "polygon"
        self.push("geometry", 0)
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("linearring", attrs_d))

    def _start_gml_pos(self, attrs_d):
        self.push("pos", 0)
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("pos", attrs_d))

    def _end_gml_pos(self):
        this = self.pop("pos")
        context = self._get_context()
        srs_name = context["where"].get("srsName")
        srs_dimension = context["where"].get("srsDimension", 2)
        swap = True
        if srs_name and "EPSG" in srs_name:
            epsg = int(srs_name.split(":")[-1])
            swap = bool(epsg in _geogCS)
        geometry = _parse_georss_point(this, swap=swap, dims=srs_dimension)
        if geometry:
            self._save_where(geometry)
        if self.geometries:
            self._gml_collect_positions(this)

    def _start_gml_poslist(self, attrs_d):
        self.push("pos", 0)
        if self.geometries:
            self._geom_stack.append(_new_gml_frame("poslist", attrs_d))

    def _end_gml_poslist(self):
        this = self.pop("pos")
        context = self._get_context()
        srs_name = context["where"].get("srsName")
        srs_dimension = context["where"].get("srsDimension", 2)
        swap = True
        if srs_name and "EPSG" in srs_name:
            epsg = int(srs_name.split(":")[-1])
            swap = bool(epsg in _geogCS)
        geometry = _parse_poslist(this, self.ingeometry, swap=swap, dims=srs_dimension)
        if geometry:
            self._save_where(geometry)
        if self.geometries:
            self._gml_collect_positions(this)

    def _end_geom(self):
        self.ingeometry = 0
        self.pop("geometry")

    def _end_gml_point(self):
        self._end_geom()
        if self.geometries:
            self._gml_finish_positions_geometry("point")

    def _end_gml_linestring(self):
        self._end_geom()
        if self.geometries:
            self._gml_finish_positions_geometry("linestring")

    def _end_gml_linearring(self):
        self._end_geom()
        if self.geometries:
            self._gml_finish_linearring()

    def _end_gml_exterior(self):
        self._end_geom()
        if (
            self.geometries
            and self._geom_stack
            and self._geom_stack[-1]["kind"] == "exterior"
        ):
            self._geom_stack.pop()

    def _end_gml_interior(self):
        if not self.geometries:
            # Replicate the historical fallback for elements without
            # a handler; see _start_gml_interior().
            self.pop("gml_interior")
            return
        if self._geom_stack and self._geom_stack[-1]["kind"] == "interior":
            self._geom_stack.pop()

    def _end_gml_polygon(self):
        self._end_geom()
        if not self.geometries:
            return
        if not self._geom_stack or self._geom_stack[-1]["kind"] != "polygon":
            return
        frame = self._geom_stack.pop()
        error = frame["error"]
        if error is None and frame["exterior"] is None:
            error = "polygon has no exterior ring"
        if error is not None:
            self._diagnose_geometry(error)
            return
        self._emit_geometry(
            {"type": "Polygon", "coordinates": [frame["exterior"], *frame["interiors"]]}
        )

    def _end_where(self):
        self.pop("where")

    _end_georss_where = _end_where

    # Everything below supports the opt-in ``geometries`` mode.

    def _collect_simple_geometry(self, kind, text):
        """Validate a GeoRSS Simple geometry and append it to the context."""

        try:
            positions = _parse_positions(text or "", None, 2)
            if kind == "point":
                geometry = _build_point(positions)
            elif kind == "linestring":
                geometry = _build_linestring(positions)
            else:
                geometry = {"type": "Polygon", "coordinates": [_build_ring(positions)]}
        except _GeometryError as exc:
            self._diagnose_geometry(str(exc))
            return
        self._emit_geometry(geometry)

    def _gml_collect_positions(self, text):
        """Parse a gml:pos/gml:posList body into the enclosing GML geometry."""

        # The effective srsName/srsDimension are scoped: the nearest
        # enclosing element that declares them wins, and the values never
        # leak to sibling elements because each element's frame is popped
        # when the element ends.
        srs_name, srs_dimension = self._gml_effective_srs()
        if self._geom_stack and self._geom_stack[-1]["kind"] in ("pos", "poslist"):
            self._geom_stack.pop()
        try:
            dims = _resolve_dimension(srs_dimension)
            positions = _parse_positions(text or "", srs_name, dims)
        except _GeometryError as exc:
            self._gml_fail(str(exc))
            return
        for frame in reversed(self._geom_stack):
            if "positions" in frame:
                frame["positions"].extend(positions)
                return

    def _gml_effective_srs(self):
        srs_name = None
        srs_dimension = None
        for frame in reversed(self._geom_stack):
            if srs_name is None and frame.get("srs_name") is not None:
                srs_name = frame["srs_name"]
            if srs_dimension is None and frame.get("srs_dimension") is not None:
                srs_dimension = frame["srs_dimension"]
        return srs_name, srs_dimension

    def _gml_fail(self, message):
        """Mark the innermost GML geometry being built as invalid."""

        for frame in reversed(self._geom_stack):
            if frame["kind"] in ("point", "linestring", "linearring", "polygon"):
                if frame.get("error") is None:
                    frame["error"] = message
                return

    def _gml_finish_positions_geometry(self, kind):
        if not self._geom_stack or self._geom_stack[-1]["kind"] != kind:
            return
        frame = self._geom_stack.pop()
        error = frame["error"]
        if error is None:
            try:
                if kind == "point":
                    geometry = _build_point(frame["positions"])
                else:
                    geometry = _build_linestring(frame["positions"])
            except _GeometryError as exc:
                error = str(exc)
        if error is not None:
            self._diagnose_geometry(error)
            return
        self._emit_geometry(geometry)

    def _gml_finish_linearring(self):
        if not self._geom_stack or self._geom_stack[-1]["kind"] != "linearring":
            return
        frame = self._geom_stack.pop()
        error = frame["error"]
        ring = None
        if error is None:
            try:
                ring = _build_ring(frame["positions"])
            except _GeometryError as exc:
                error = str(exc)
        # Find the enclosing polygon, if any, and whether this ring is
        # its exterior ring or one of its interior rings.
        polygon_frame = None
        target = "exterior"
        parent = self._geom_stack[-1] if self._geom_stack else None
        if parent is not None and parent["kind"] in ("exterior", "interior"):
            target = parent["kind"]
            if len(self._geom_stack) >= 2 and self._geom_stack[-2]["kind"] == "polygon":
                polygon_frame = self._geom_stack[-2]
        elif parent is not None and parent["kind"] == "polygon":
            # Leniently treat a LinearRing placed directly inside
            # a Polygon as the exterior ring.
            polygon_frame = parent
        if polygon_frame is not None:
            if error is not None:
                if polygon_frame["error"] is None:
                    polygon_frame["error"] = error
            elif target == "exterior":
                if polygon_frame["exterior"] is None:
                    polygon_frame["exterior"] = ring
                elif polygon_frame["error"] is None:
                    polygon_frame["error"] = "polygon has multiple exterior rings"
            else:
                polygon_frame["interiors"].append(ring)
            return
        # A standalone LinearRing is exposed as a polygon with a single ring.
        if error is not None:
            self._diagnose_geometry(error)
            return
        self._emit_geometry({"type": "Polygon", "coordinates": [ring]})

    def _emit_geometry(self, geometry):
        context = self._get_context()
        self._next_geometry_ordinal(context)
        context.setdefault("geometries", []).append(geometry)

    def _diagnose_geometry(self, message):
        context = self._get_context()
        ordinal = self._next_geometry_ordinal(context)
        entry = len(self.entries) - 1 if self.inentry else None
        self.geometries_diagnostics.append(
            FeedParserDict(entry=entry, geometry=ordinal, message=message)
        )

    def _next_geometry_ordinal(self, context):
        key = id(context)
        ordinal = self._geom_ordinals.get(key, 0)
        self._geom_ordinals[key] = ordinal + 1
        return ordinal


# Helpers for the opt-in ``geometries`` mode. Coordinates are emitted as
# (longitude, latitude) or (longitude, latitude, altitude) tuples, matching
# the GeoJSON ordering; GeoRSS and GML encode WGS 84 as (lat, lon[, alt]).


def _new_gml_frame(kind, attrs_d):
    frame = {
        "kind": kind,
        "error": None,
        "srs_name": attrs_d.get("srsname"),
        "srs_dimension": attrs_d.get("srsdimension"),
    }
    if kind in ("point", "linestring", "linearring"):
        frame["positions"] = []
    elif kind == "polygon":
        frame["exterior"] = None
        frame["interiors"] = []
    return frame


def _resolve_dimension(raw):
    if raw is None:
        return 2
    try:
        dims = int(raw)
    except (TypeError, ValueError):
        raise _GeometryError(f"invalid srsDimension {raw!r}")
    if dims not in (2, 3):
        raise _GeometryError(f"unsupported srsDimension {raw!r}")
    return dims


def _parse_positions(value, srs_name, dims):
    # Parse whitespace- or comma-separated coordinates into a list of
    # (lon, lat[, alt]) tuples. Only WGS 84 (an absent srsName) and
    # urn:ogc:def:crs:EPSG::4326 are supported; both order coordinates
    # as (lat, lon[, alt]), so the first two ordinates are swapped.
    if srs_name is not None and srs_name.strip().lower() != _SUPPORTED_SRS_NAME:
        raise _GeometryError(f"unsupported srsName {srs_name!r}")
    tokens = value.replace(",", " ").split()
    if not tokens:
        raise _GeometryError("no coordinates found")
    if len(tokens) % dims:
        raise _GeometryError(
            f"coordinate count {len(tokens)} is not a multiple of dimension {dims}"
        )
    values = []
    for token in tokens:
        try:
            number = float(token)
        except ValueError:
            raise _GeometryError(f"invalid coordinate {token!r}")
        if not math.isfinite(number):
            raise _GeometryError(f"non-finite coordinate {token!r}")
        values.append(number)
    positions = []
    for i in range(0, len(values), dims):
        group = values[i : i + dims]
        positions.append((group[1], group[0], *group[2:]))
    return positions


def _check_consistent_dimensions(positions):
    if len({len(position) for position in positions}) > 1:
        raise _GeometryError("positions have inconsistent dimensions")


def _build_point(positions):
    if len(positions) != 1:
        raise _GeometryError(
            f"point requires exactly 1 position, found {len(positions)}"
        )
    return {"type": "Point", "coordinates": positions[0]}


def _build_linestring(positions):
    if len(positions) < 2:
        raise _GeometryError(
            f"line requires at least 2 positions, found {len(positions)}"
        )
    _check_consistent_dimensions(positions)
    return {"type": "LineString", "coordinates": positions}


def _build_ring(positions):
    if len(positions) < 4:
        raise _GeometryError(
            f"polygon ring requires at least 4 positions, found {len(positions)}"
        )
    _check_consistent_dimensions(positions)
    if positions[0] != positions[-1]:
        raise _GeometryError("polygon ring is not closed")
    return positions


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
