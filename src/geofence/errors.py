"""Exception hierarchy used across the package.

Every error raised on purpose by geofence derives from :class:`GeofenceError`,
so callers can catch the whole family with one ``except`` clause.  The more
specific classes also derive from the matching built-in (``ValueError``,
``ArithmeticError`` ...) so that code written against the built-ins keeps
working.
"""

from __future__ import annotations


class GeofenceError(Exception):
    """Base class for all errors raised by this package."""


class ValidationError(GeofenceError, ValueError):
    """A value is outside its allowed domain."""


class InvalidCoordinateError(ValidationError):
    """A latitude or longitude is not finite or is out of range."""


class InvalidGeometryError(ValidationError):
    """A ring, polygon, line or bounding box is structurally invalid."""


class UnitError(ValidationError):
    """An unknown unit name was given to a conversion helper."""


class GeohashError(ValidationError):
    """A geohash string or precision is invalid."""


class ConvergenceError(GeofenceError, ArithmeticError):
    """An iterative geodesic solution did not converge.

    ``iterations`` holds the number of iterations that were attempted.
    """

    def __init__(self, message: str, iterations: int) -> None:
        super().__init__(message)
        self.iterations = iterations


class ParseError(GeofenceError, ValueError):
    """Base class for errors raised while reading text formats."""


class WktParseError(ParseError):
    """Malformed WKT.

    ``position`` is the zero-based character offset at which the problem was
    detected, or ``None`` when the problem is not tied to one place.
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        if position is not None:
            message = f"{message} (at offset {position})"
        super().__init__(message)
        self.position = position


class GeoJsonParseError(ParseError):
    """Malformed or unsupported GeoJSON.

    ``path`` is a JSON-pointer-like location such as ``$.features[2].geometry``.
    """

    def __init__(self, message: str, path: str = "$") -> None:
        super().__init__(f"{path}: {message}")
        self.path = path


class TrackParseError(ParseError):
    """Malformed track CSV.

    ``line`` is the one-based line number in the input, when known.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        if line is not None:
            message = f"line {line}: {message}"
        super().__init__(message)
        self.line = line


class EngineError(GeofenceError):
    """Base class for errors raised by the geofence engine."""


class DuplicateFenceError(EngineError, ValueError):
    """A fence id was registered twice."""


class UnknownFenceError(EngineError, KeyError):
    """A fence id is not registered."""

    def __str__(self) -> str:  # KeyError would otherwise repr() the message
        return str(self.args[0]) if self.args else ""


class OutOfOrderError(EngineError, ValueError):
    """A position update is older than the previous one for the same device."""
