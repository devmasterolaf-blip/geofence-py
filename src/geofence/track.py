"""Reading device tracks from CSV.

A track file has a header row followed by one fix per row.  Column names are
matched case-insensitively:

========== ====================================== =========
column     accepted names                         required
========== ====================================== =========
timestamp  ``timestamp``, ``time``, ``ts``        yes
latitude   ``lat``, ``latitude``                  yes
longitude  ``lon``, ``lng``, ``longitude``        yes
device     ``device``, ``device_id``, ``id``      no
========== ====================================== =========

Timestamps are either numbers (seconds, typically Unix time) or ISO-8601
date-times such as ``2026-03-01T08:15:00Z``; a date-time without an offset is
taken as UTC.  Rows without a device column belong to :data:`DEFAULT_DEVICE`.
Other columns are ignored, as are blank lines.

Problems raise :class:`~geofence.errors.TrackParseError` with the one-based
line number of the offending row.
"""

from __future__ import annotations

import csv
import math
import os
from datetime import datetime, timezone
from typing import Iterable, Union

from .coords import Coordinate
from .engine import Position
from .errors import InvalidCoordinateError, TrackParseError

#: Device id used when the file has no device column.
DEFAULT_DEVICE = "device"

_COLUMN_NAMES = {
    "timestamp": ("timestamp", "time", "ts"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "longitude"),
    "device": ("device", "device_id", "id"),
}
_REQUIRED = ("timestamp", "lat", "lon")


def parse_timestamp(text: str) -> float:
    """Convert a numeric or ISO-8601 timestamp into seconds since the epoch.

    Raises :class:`ValueError` when the text is neither.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty timestamp")
    try:
        seconds = float(stripped)
    except ValueError:
        pass
    else:
        if not math.isfinite(seconds):
            raise ValueError(f"timestamp is not finite: {stripped!r}")
        return seconds
    iso = stripped[:-1] + "+00:00" if stripped[-1] in "zZ" else stripped
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError(
            f"timestamp is neither a number nor an ISO-8601 date-time: {stripped!r}"
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def format_timestamp(seconds: float) -> str:
    """Render epoch seconds as an ISO-8601 UTC date-time ending in ``Z``."""
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    spec = "seconds" if moment.microsecond == 0 else "milliseconds"
    return moment.isoformat(timespec=spec).replace("+00:00", "Z")


def _map_header(header: list[str], line: int) -> dict[str, int]:
    names = [cell.strip().lower() for cell in header]
    columns: dict[str, int] = {}
    for field, accepted in _COLUMN_NAMES.items():
        matches = [index for index, name in enumerate(names) if name in accepted]
        if len(matches) > 1:
            raise TrackParseError(f"more than one {field} column in the header", line)
        if matches:
            columns[field] = matches[0]
    missing = [field for field in _REQUIRED if field not in columns]
    if missing:
        raise TrackParseError(
            "header is missing required column(s): " + ", ".join(missing), line
        )
    return columns


def _number(row: list[str], index: int, what: str, line: int) -> float:
    text = row[index].strip()
    try:
        value = float(text)
    except ValueError:
        raise TrackParseError(f"{what} is not a number: {text!r}", line) from None
    return value


def parse_track(lines: Iterable[str]) -> list[Position]:
    """Parse CSV lines (header first) into positions, in file order."""
    reader = csv.reader(lines)
    columns: dict[str, int] | None = None
    width = 0
    positions: list[Position] = []
    try:
        for row in reader:
            line = reader.line_num
            if not row or all(not cell.strip() for cell in row):
                continue
            if columns is None:
                columns = _map_header(row, line)
                width = max(columns.values()) + 1
                continue
            if len(row) < width:
                raise TrackParseError(
                    f"expected at least {width} fields, got {len(row)}", line
                )
            try:
                timestamp = parse_timestamp(row[columns["timestamp"]])
            except ValueError as exc:
                raise TrackParseError(str(exc), line) from None
            lat = _number(row, columns["lat"], "latitude", line)
            lon = _number(row, columns["lon"], "longitude", line)
            try:
                point = Coordinate(lat, lon)
            except InvalidCoordinateError as exc:
                raise TrackParseError(str(exc), line) from None
            device = DEFAULT_DEVICE
            if "device" in columns:
                device = row[columns["device"]].strip()
                if not device:
                    raise TrackParseError("device id is empty", line)
            positions.append(Position(device, timestamp, point))
    except csv.Error as exc:
        raise TrackParseError(f"malformed CSV: {exc}", reader.line_num) from None
    if columns is None:
        raise TrackParseError("track is empty: no header row found")
    return positions


def read_track(path: Union[str, os.PathLike]) -> list[Position]:
    """Read positions from a UTF-8 CSV file (see :func:`parse_track`)."""
    with open(path, encoding="utf-8", newline="") as handle:
        return parse_track(handle)


def sort_track(positions: Iterable[Position]) -> list[Position]:
    """Order positions by time, keeping file order among equal timestamps."""
    return sorted(positions, key=lambda position: position.timestamp)
