"""Geofence engine: per-device position streams in, enter/exit/dwell events out.

The engine keeps, for every device, the set of fences it is currently inside.
Each call to :meth:`GeofenceEngine.update` compares the new position with
that set and reports what changed.

Two mechanisms keep a device that sits near a boundary from flapping:

* ``hysteresis_m`` -- a device enters as soon as it is inside a fence (the
  boundary counts as inside) but only leaves once it is *more than* this many
  metres outside it.
* ``confirmations`` -- a transition is only reported after this many
  consecutive samples agree with it.

Timestamps are plain numbers in seconds (typically Unix time).  Updates for
one device must not go back in time; different devices are independent.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from .coords import Coordinate, CoordinateLike, as_coordinate
from .errors import OutOfOrderError, ValidationError
from .fence import Fence
from .index import FenceIndex


class EventType(str, enum.Enum):
    """Kind of transition reported by the engine."""

    ENTER = "enter"
    EXIT = "exit"
    DWELL = "dwell"


@dataclass(frozen=True)
class Position:
    """One timestamped fix for a device."""

    device_id: str
    timestamp: float
    point: Coordinate


@dataclass(frozen=True)
class Event:
    """A transition of one device relative to one fence.

    ``duration_s`` is the time since the matching ``ENTER`` event: zero for
    ``ENTER`` itself, the stay so far for ``DWELL`` and the whole visit for
    ``EXIT``.  ``point`` is the position that triggered the event.
    """

    type: EventType
    device_id: str
    fence_id: str
    timestamp: float
    point: Coordinate
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """A JSON-friendly representation."""
        return {
            "type": self.type.value,
            "device": self.device_id,
            "fence": self.fence_id,
            "timestamp": self.timestamp,
            "lat": self.point.lat,
            "lon": self.point.lon,
            "duration_s": self.duration_s,
        }


class _Visit:
    __slots__ = ("entered_at", "dwell_reported")

    def __init__(self, entered_at: float) -> None:
        self.entered_at = entered_at
        self.dwell_reported = False


class _DeviceState:
    __slots__ = ("timestamp", "point", "visits", "enter_streak", "exit_streak")

    def __init__(self, timestamp: float, point: Coordinate) -> None:
        self.timestamp = timestamp
        self.point = point
        self.visits: dict[str, _Visit] = {}
        self.enter_streak: dict[str, int] = {}
        self.exit_streak: dict[str, int] = {}


def _check_timestamp(timestamp: Any) -> float:
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValidationError(f"timestamp must be a number of seconds, got {timestamp!r}")
    if not math.isfinite(timestamp):
        raise ValidationError(f"timestamp must be finite, got {timestamp!r}")
    return float(timestamp)


class GeofenceEngine:
    """Tracks devices against a set of fences and emits transition events.

    Parameters
    ----------
    fences:
        Initial fences; more can be added with :meth:`add_fence`.
    hysteresis_m:
        Exit margin in metres.  ``0`` means a device leaves as soon as a
        sample falls outside the fence.
    dwell_s:
        When set, one ``DWELL`` event per visit is emitted by the first
        update that arrives at least this many seconds after the ``ENTER``.
    confirmations:
        Number of consecutive agreeing samples needed before an ``ENTER`` or
        ``EXIT`` is reported.  The event carries the time and position of the
        confirming sample.
    cell_size_deg:
        Cell size of the underlying grid index.
    """

    def __init__(
        self,
        fences: Iterable[Fence] = (),
        *,
        hysteresis_m: float = 0.0,
        dwell_s: float | None = None,
        confirmations: int = 1,
        cell_size_deg: float = 0.25,
    ) -> None:
        if isinstance(hysteresis_m, bool) or not isinstance(hysteresis_m, (int, float)):
            raise ValidationError(f"hysteresis_m must be a number, got {hysteresis_m!r}")
        if not math.isfinite(hysteresis_m) or hysteresis_m < 0:
            raise ValidationError(f"hysteresis_m must be finite and >= 0, got {hysteresis_m!r}")
        if dwell_s is not None:
            if isinstance(dwell_s, bool) or not isinstance(dwell_s, (int, float)):
                raise ValidationError(f"dwell_s must be a number or None, got {dwell_s!r}")
            if not math.isfinite(dwell_s) or dwell_s <= 0:
                raise ValidationError(f"dwell_s must be finite and > 0, got {dwell_s!r}")
        if isinstance(confirmations, bool) or not isinstance(confirmations, int):
            raise ValidationError(f"confirmations must be an integer, got {confirmations!r}")
        if confirmations < 1:
            raise ValidationError(f"confirmations must be >= 1, got {confirmations}")
        self._hysteresis_m = float(hysteresis_m)
        self._dwell_s = None if dwell_s is None else float(dwell_s)
        self._confirmations = confirmations
        self._index = FenceIndex(fences, cell_size_deg=cell_size_deg)
        self._devices: dict[str, _DeviceState] = {}

    # -- configuration -----------------------------------------------------

    @property
    def hysteresis_m(self) -> float:
        return self._hysteresis_m

    @property
    def dwell_s(self) -> float | None:
        return self._dwell_s

    @property
    def confirmations(self) -> int:
        return self._confirmations

    @property
    def fences(self) -> list[Fence]:
        """All registered fences, ordered by id."""
        return list(self._index)

    def add_fence(self, fence: Fence) -> None:
        """Register a fence; raises :class:`DuplicateFenceError` on a known id.

        A device that is already inside the new fence gets its ``ENTER`` on
        its next update.
        """
        self._index.add(fence)

    def remove_fence(self, fence_id: str) -> Fence:
        """Unregister a fence; raises :class:`UnknownFenceError` if absent.

        Visits to the removed fence are dropped without ``EXIT`` events.
        """
        fence = self._index.remove(fence_id)
        for state in self._devices.values():
            state.visits.pop(fence_id, None)
            state.enter_streak.pop(fence_id, None)
            state.exit_streak.pop(fence_id, None)
        return fence

    # -- device state ------------------------------------------------------

    def devices(self) -> list[str]:
        """Ids of all devices seen so far, sorted."""
        return sorted(self._devices)

    def inside(self, device_id: str) -> tuple[str, ...]:
        """Ids of the fences the device is currently inside, sorted.

        An unknown device is inside nothing.
        """
        state = self._devices.get(device_id)
        return tuple(sorted(state.visits)) if state else ()

    def occupants(self, fence_id: str) -> list[str]:
        """Ids of the devices currently inside the given fence, sorted."""
        self._index.get(fence_id)
        return sorted(
            device_id for device_id, state in self._devices.items() if fence_id in state.visits
        )

    def last_position(self, device_id: str) -> Position | None:
        """The most recent fix of a device, or ``None`` if it was never seen."""
        state = self._devices.get(device_id)
        if state is None:
            return None
        return Position(device_id, state.timestamp, state.point)

    def forget(self, device_id: str) -> bool:
        """Drop all state for a device; returns whether it was known."""
        return self._devices.pop(device_id, None) is not None

    # -- updates -----------------------------------------------------------

    def update(self, device_id: str, timestamp: float, point: CoordinateLike) -> list[Event]:
        """Feed one position and return the events it triggers.

        Events are ordered exits first, then enters, then dwells, each group
        sorted by fence id.  Raises :class:`OutOfOrderError` when the
        timestamp is earlier than the device's previous one; the stored state
        is left untouched in that case.
        """
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValidationError(f"device id must be a non-empty string, got {device_id!r}")
        when = _check_timestamp(timestamp)
        here = as_coordinate(point)

        state = self._devices.get(device_id)
        if state is None:
            state = self._devices[device_id] = _DeviceState(when, here)
        elif when < state.timestamp:
            raise OutOfOrderError(
                f"device {device_id!r}: timestamp {when:g} is earlier than the "
                f"previous update at {state.timestamp:g}"
            )
        else:
            state.timestamp = when
            state.point = here

        containing = {fence.id for fence in self._index.containing(here)}
        events: list[Event] = []
        events.extend(self._exits(device_id, state, containing))
        events.extend(self._enters(device_id, state, containing))
        if self._dwell_s is not None:
            events.extend(self._dwells(device_id, state))
        return events

    def _exits(self, device_id: str, state: _DeviceState, containing: set[str]) -> Iterator[Event]:
        for fence_id in sorted(state.visits):
            if fence_id in containing or self._within_margin(fence_id, state.point):
                state.exit_streak.pop(fence_id, None)
                continue
            streak = state.exit_streak.get(fence_id, 0) + 1
            if streak < self._confirmations:
                state.exit_streak[fence_id] = streak
                continue
            state.exit_streak.pop(fence_id, None)
            visit = state.visits.pop(fence_id)
            yield Event(
                EventType.EXIT,
                device_id,
                fence_id,
                state.timestamp,
                state.point,
                state.timestamp - visit.entered_at,
            )

    def _within_margin(self, fence_id: str, point: Coordinate) -> bool:
        if self._hysteresis_m <= 0.0:
            return False
        return self._index.get(fence_id).signed_distance(point) <= self._hysteresis_m

    def _enters(self, device_id: str, state: _DeviceState, containing: set[str]) -> Iterator[Event]:
        for fence_id in [f for f in state.enter_streak if f not in containing]:
            del state.enter_streak[fence_id]
        for fence_id in sorted(containing):
            if fence_id in state.visits:
                continue
            streak = state.enter_streak.get(fence_id, 0) + 1
            if streak < self._confirmations:
                state.enter_streak[fence_id] = streak
                continue
            state.enter_streak.pop(fence_id, None)
            state.visits[fence_id] = _Visit(state.timestamp)
            yield Event(EventType.ENTER, device_id, fence_id, state.timestamp, state.point)

    def _dwells(self, device_id: str, state: _DeviceState) -> Iterator[Event]:
        for fence_id in sorted(state.visits):
            visit = state.visits[fence_id]
            stay = state.timestamp - visit.entered_at
            if visit.dwell_reported or stay < self._dwell_s:
                continue
            visit.dwell_reported = True
            yield Event(EventType.DWELL, device_id, fence_id, state.timestamp, state.point, stay)

    def process(self, positions: Iterable[Position]) -> Iterator[Event]:
        """Feed many positions in order, yielding events as they occur."""
        for position in positions:
            yield from self.update(position.device_id, position.timestamp, position.point)
