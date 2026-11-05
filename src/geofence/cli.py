"""Command line interface: ``geofence <command> ...``.

Exit codes
----------
0  success
1  the command ran but the answer is "no" (``contains`` matched no fence)
2  bad command line (unknown option, malformed coordinate, ...)
3  an input file or value was read but is not valid
4  an input file could not be read
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Callable, Sequence

from . import __version__, geohash, geojson, wkt
from .bbox import BoundingBox
from .coords import Coordinate
from .engine import Event, GeofenceEngine
from .errors import GeofenceError, GeoJsonParseError, OutOfOrderError
from .geodesy import DISTANCE_METHODS, distance, initial_bearing
from .index import FenceIndex
from .polyline import LineString
from .track import format_timestamp, read_track, sort_track
from .units import METERS_PER_UNIT, format_distance

EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_USAGE = 2
EXIT_DATA = 3
EXIT_IO = 4

_NEGATIVE_NUMBER_LIKE = re.compile(r"^-\.?\d")


def _point(text: str) -> Coordinate:
    try:
        return Coordinate.parse(text)
    except GeofenceError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _box(text: str) -> BoundingBox:
    parts = text.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"expected 'south,west,north,east', got {text!r}")
    try:
        south, west, north, east = (float(part) for part in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected four numbers 'south,west,north,east', got {text!r}"
        ) from None
    try:
        return BoundingBox(south, west, north, east)
    except GeofenceError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _non_negative(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {text!r}") from None
    if not value >= 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"expected a finite number >= 0, got {text!r}")
    return value


def _positive(text: str) -> float:
    value = _non_negative(text)
    if value == 0:
        raise argparse.ArgumentTypeError("expected a number > 0, got 0")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected an integer >= 1, got {value}")
    return value


def _precision(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected an integer >= 0, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geofence",
        description="Geodesy, geohash and geofencing tools for latitude/longitude data.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p = commands.add_parser("distance", help="distance between two points")
    p.add_argument("origin", type=_point, metavar="LAT,LON")
    p.add_argument("target", type=_point, metavar="LAT,LON")
    p.add_argument("--method", choices=DISTANCE_METHODS, default="auto")
    p.add_argument("--unit", choices=sorted(METERS_PER_UNIT), default="m")
    p.add_argument("--precision", type=_precision, default=3, help="decimals to print")
    p.add_argument("--bearing", action="store_true", help="also print the initial bearing")
    p.set_defaults(handler=_cmd_distance)

    p = commands.add_parser(
        "contains",
        help="list the fences that contain a point",
        description="Prints 'id<TAB>name' for every fence containing the point. "
        "Exits with status 1 when no fence does.",
    )
    p.add_argument("fences", metavar="FENCES.geojson")
    p.add_argument("point", type=_point, metavar="LAT,LON")
    p.add_argument(
        "--exclude-boundary",
        action="store_true",
        help="do not count points exactly on a fence boundary",
    )
    p.set_defaults(handler=_cmd_contains)

    p = commands.add_parser(
        "simplify",
        help="simplify a line with Douglas-Peucker",
        description="Reads a WKT LINESTRING or a GeoJSON LineString (geometry or Feature) "
        "from a file, or from standard input when INPUT is '-'.",
    )
    p.add_argument("input", metavar="INPUT")
    p.add_argument("--tolerance", type=_non_negative, required=True, metavar="METRES")
    p.add_argument(
        "--format", choices=("wkt", "geojson"), default=None, help="output format (default: same as input)"
    )
    p.add_argument("--precision", type=_precision, default=6, help="decimals in WKT output")
    p.set_defaults(handler=_cmd_simplify)

    p = commands.add_parser("geohash", help="encode, decode and explore geohashes")
    actions = p.add_subparsers(dest="action", metavar="ACTION", required=True)
    a = actions.add_parser("encode", help="geohash of a point")
    a.add_argument("point", type=_point, metavar="LAT,LON")
    a.add_argument("--precision", type=_positive_int, default=9)
    a.set_defaults(handler=_cmd_geohash_encode)
    a = actions.add_parser("decode", help="centre and bounds of a geohash cell")
    a.add_argument("hash", metavar="GEOHASH")
    a.set_defaults(handler=_cmd_geohash_decode)
    a = actions.add_parser("neighbors", help="the cells around a geohash")
    a.add_argument("hash", metavar="GEOHASH")
    a.set_defaults(handler=_cmd_geohash_neighbors)
    a = actions.add_parser("cover", help="cells covering a bounding box")
    a.add_argument("box", type=_box, metavar="SOUTH,WEST,NORTH,EAST")
    a.add_argument("--precision", type=_positive_int, default=5)
    a.add_argument("--max-cells", type=_positive_int, default=4096)
    a.set_defaults(handler=_cmd_geohash_cover)

    p = commands.add_parser(
        "events",
        help="replay a CSV track against fences and print enter/exit/dwell events",
    )
    p.add_argument("fences", metavar="FENCES.geojson")
    p.add_argument("track", metavar="TRACK.csv")
    p.add_argument("--hysteresis", type=_non_negative, default=0.0, metavar="METRES",
                   help="exit margin: leave a fence only when this far outside it")
    p.add_argument("--dwell", type=_positive, default=None, metavar="SECONDS",
                   help="emit a dwell event after this long inside a fence")
    p.add_argument("--confirm", type=_positive_int, default=1, metavar="N",
                   help="consecutive samples needed to confirm a transition")
    p.add_argument("--sort", action="store_true", help="sort the track by time before replaying it")
    p.add_argument("--format", choices=("text", "json"), default="text",
                   help="tab-separated text or one JSON object per line")
    p.set_defaults(handler=_cmd_events)
    return parser


def _cmd_distance(args: argparse.Namespace) -> int:
    metres = distance(args.origin, args.target, method=args.method)
    print(format_distance(metres, args.unit, args.precision))
    if args.bearing:
        if args.origin.same_place(args.target):
            print("initial bearing undefined (same point)")
        else:
            print(f"initial bearing {initial_bearing(args.origin, args.target):.3f} deg")
    return EXIT_OK


def _cmd_contains(args: argparse.Namespace) -> int:
    index = FenceIndex(geojson.read_fences(args.fences))
    matches = index.containing(args.point, boundary=not args.exclude_boundary)
    for fence in matches:
        print(f"{fence.id}\t{fence.name}")
    return EXIT_OK if matches else EXIT_NO_MATCH


def _read_text(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    with open(source, encoding="utf-8") as handle:
        return handle.read()


def _load_line(text: str) -> tuple[LineString, str]:
    """Return the line found in ``text`` and the format it was written in."""
    if text.lstrip().startswith("{"):
        document = geojson.loads(text)
        path = "$"
        if isinstance(document, dict) and document.get("type") == "Feature":
            document, path = document.get("geometry"), "$.geometry"
        geometry = geojson.parse_geometry(document, path)
        if not isinstance(geometry, LineString):
            raise GeoJsonParseError("expected a LineString geometry", f"{path}.type")
        return geometry, "geojson"
    geometry = wkt.loads(text)
    if not isinstance(geometry, LineString):
        raise wkt.WktParseError("expected a LINESTRING", 0)
    return geometry, "wkt"


def _cmd_simplify(args: argparse.Namespace) -> int:
    line, source_format = _load_line(_read_text(args.input))
    simplified = line.simplify(args.tolerance)
    if (args.format or source_format) == "wkt":
        print(wkt.dumps(simplified, precision=args.precision))
    else:
        print(json.dumps(geojson.geometry_to_dict(simplified)))
    print(f"{len(line.coords)} -> {len(simplified.coords)} points", file=sys.stderr)
    return EXIT_OK


def _cmd_geohash_encode(args: argparse.Namespace) -> int:
    print(geohash.encode(args.point, args.precision))
    return EXIT_OK


def _cmd_geohash_decode(args: argparse.Namespace) -> int:
    box = geohash.bounds(args.hash)
    centre = geohash.decode(args.hash)
    print(f"center {centre.lat:.8f},{centre.lon:.8f}")
    print(f"south {box.south:.8f}")
    print(f"west {box.west:.8f}")
    print(f"north {box.north:.8f}")
    print(f"east {box.east:.8f}")
    return EXIT_OK


def _cmd_geohash_neighbors(args: argparse.Namespace) -> int:
    for direction, cell in geohash.neighbors(args.hash).items():
        print(f"{direction}\t{cell}")
    return EXIT_OK


def _cmd_geohash_cover(args: argparse.Namespace) -> int:
    for cell in geohash.covering(args.box, args.precision, max_cells=args.max_cells):
        print(cell)
    return EXIT_OK


def _format_event(event: Event) -> str:
    fields = [format_timestamp(event.timestamp), event.device_id, event.type.value, event.fence_id]
    if event.type.value != "enter":
        fields.append(f"{event.duration_s:g}s")
    return "\t".join(fields)


def _cmd_events(args: argparse.Namespace) -> int:
    fences = geojson.read_fences(args.fences)
    track = read_track(args.track)
    if args.sort:
        track = sort_track(track)
    engine = GeofenceEngine(
        fences, hysteresis_m=args.hysteresis, dwell_s=args.dwell, confirmations=args.confirm
    )
    count = 0
    try:
        for event in engine.process(track):
            count += 1
            if args.format == "json":
                print(json.dumps(event.to_dict()))
            else:
                print(_format_event(event))
    except OutOfOrderError as exc:
        raise OutOfOrderError(f"{exc}; pass --sort to order the track by time") from None
    print(
        f"{count} event(s) from {len(track)} position(s), "
        f"{len(engine.devices())} device(s), {len(fences)} fence(s)",
        file=sys.stderr,
    )
    return EXIT_OK


def _protect_negative_numbers(argv: Sequence[str]) -> list[str]:
    """Stop argparse from reading ``-33.9,18.4`` as an option.

    argparse treats any argument containing a space as a positional value, and
    every numeric parser in this module ignores surrounding whitespace.
    """
    return [" " + arg if _NEGATIVE_NUMBER_LIKE.match(arg) else arg for arg in argv]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its exit status instead of exiting."""
    parser = build_parser()
    raw = sys.argv[1:] if argv is None else argv
    try:
        args = parser.parse_args(_protect_negative_numbers(raw))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except GeofenceError as exc:
        print(f"geofence: error: {exc}", file=sys.stderr)
        return EXIT_DATA
    except UnicodeDecodeError as exc:
        print(f"geofence: error: input is not valid UTF-8: {exc}", file=sys.stderr)
        return EXIT_DATA
    except OSError as exc:
        target = f"{exc.filename}: " if exc.filename else ""
        print(f"geofence: error: {target}{exc.strerror or exc}", file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    sys.exit(main())
