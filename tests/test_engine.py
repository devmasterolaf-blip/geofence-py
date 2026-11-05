import math

import pytest

from geofence.circle import Circle
from geofence.coords import Coordinate
from geofence.engine import Event, EventType, GeofenceEngine, Position
from geofence.errors import (
    DuplicateFenceError,
    InvalidCoordinateError,
    OutOfOrderError,
    UnknownFenceError,
    ValidationError,
)
from geofence.fence import Fence
from geofence.geodesy import destination
from geofence.polygon import Polygon, Ring

CENTER = Coordinate(48.0, 11.0)


def at(metres_east):
    """A point the given distance east of the test fence centre."""
    return destination(CENTER, 90.0, metres_east) if metres_east else CENTER


def depot(radius=100.0, fence_id="depot"):
    return Fence(fence_id, Circle(CENTER, radius))


def kinds(events):
    return [(e.type.value, e.fence_id) for e in events]


class TestConfiguration:
    def test_defaults(self):
        engine = GeofenceEngine()
        assert engine.hysteresis_m == 0.0
        assert engine.dwell_s is None
        assert engine.confirmations == 1
        assert engine.fences == []
        assert engine.devices() == []

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"hysteresis_m": -1},
            {"hysteresis_m": math.nan},
            {"hysteresis_m": "5"},
            {"hysteresis_m": True},
            {"dwell_s": 0},
            {"dwell_s": -3},
            {"dwell_s": math.inf},
            {"dwell_s": "60"},
            {"confirmations": 0},
            {"confirmations": 1.5},
            {"confirmations": True},
        ],
    )
    def test_bad_settings_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            GeofenceEngine(**kwargs)

    def test_duplicate_initial_fences_are_rejected(self):
        with pytest.raises(DuplicateFenceError):
            GeofenceEngine([depot(), depot()])

    def test_fences_are_listed_in_id_order(self):
        engine = GeofenceEngine([depot(fence_id="b"), depot(fence_id="a")])
        assert [f.id for f in engine.fences] == ["a", "b"]


class TestEnterAndExit:
    def test_first_fix_inside_enters(self):
        engine = GeofenceEngine([depot()])
        (event,) = engine.update("truck", 100, at(0))
        assert event == Event(EventType.ENTER, "truck", "depot", 100.0, CENTER, 0.0)
        assert engine.inside("truck") == ("depot",)

    def test_first_fix_outside_is_silent(self):
        engine = GeofenceEngine([depot()])
        assert engine.update("truck", 100, at(500)) == []
        assert engine.inside("truck") == ()

    def test_enter_then_exit_reports_visit_duration(self):
        engine = GeofenceEngine([depot()])
        assert engine.update("truck", 0, at(500)) == []
        assert kinds(engine.update("truck", 10, at(50))) == [("enter", "depot")]
        assert engine.update("truck", 20, at(20)) == []
        (event,) = engine.update("truck", 45, at(300))
        assert event.type is EventType.EXIT
        assert event.duration_s == 35.0
        assert event.timestamp == 45.0
        assert event.point == at(300)
        assert engine.inside("truck") == ()

    def test_boundary_counts_as_inside(self):
        square = Fence("sq", Polygon(Ring([(0, 0), (0, 1), (1, 1), (1, 0)])))
        engine = GeofenceEngine([square])
        assert kinds(engine.update("d", 0, (0.5, 1.0))) == [("enter", "sq")]
        assert engine.update("d", 1, (1.0, 1.0)) == []
        assert kinds(engine.update("d", 2, (1.0, 1.0001))) == [("exit", "sq")]

    def test_reentry_starts_a_new_visit(self):
        engine = GeofenceEngine([depot()])
        engine.update("truck", 0, at(0))
        engine.update("truck", 10, at(500))
        (enter,) = engine.update("truck", 30, at(0))
        (exit_,) = engine.update("truck", 37, at(500))
        assert enter.type is EventType.ENTER and enter.duration_s == 0.0
        assert exit_.duration_s == 7.0

    def test_devices_are_tracked_independently(self):
        engine = GeofenceEngine([depot()])
        assert kinds(engine.update("a", 100, at(0))) == [("enter", "depot")]
        assert engine.update("b", 50, at(500)) == []
        assert kinds(engine.update("b", 60, at(0))) == [("enter", "depot")]
        assert kinds(engine.update("a", 110, at(500))) == [("exit", "depot")]
        assert engine.inside("b") == ("depot",)
        assert engine.devices() == ["a", "b"]
        assert engine.occupants("depot") == ["b"]

    def test_overlapping_fences_order_events_by_fence_id(self):
        engine = GeofenceEngine([depot(100, "inner"), depot(1000, "outer"), depot(50, "core")])
        assert kinds(engine.update("d", 0, at(0))) == [
            ("enter", "core"),
            ("enter", "inner"),
            ("enter", "outer"),
        ]
        assert kinds(engine.update("d", 1, at(70))) == [("exit", "core")]
        assert kinds(engine.update("d", 2, at(5000))) == [("exit", "inner"), ("exit", "outer")]

    def test_exits_are_reported_before_enters(self):
        west = Fence("west", Circle(at(0), 100))
        east = Fence("east", Circle(at(1000), 100))
        engine = GeofenceEngine([west, east])
        engine.update("d", 0, at(0))
        assert kinds(engine.update("d", 1, at(1000))) == [("exit", "west"), ("enter", "east")]


class TestHysteresis:
    def test_without_margin_boundary_jitter_flaps(self):
        engine = GeofenceEngine([depot()])
        seen = []
        for t, offset in enumerate([90, 105, 95, 110, 98]):
            seen.extend(kinds(engine.update("d", t, at(offset))))
        assert seen == [
            ("enter", "depot"),
            ("exit", "depot"),
            ("enter", "depot"),
            ("exit", "depot"),
            ("enter", "depot"),
        ]

    def test_margin_absorbs_boundary_jitter(self):
        engine = GeofenceEngine([depot()], hysteresis_m=25)
        seen = []
        for t, offset in enumerate([90, 105, 95, 110, 98, 124]):
            seen.extend(kinds(engine.update("d", t, at(offset))))
        assert seen == [("enter", "depot")]
        assert engine.inside("d") == ("depot",)

    def test_exit_once_beyond_the_margin(self):
        engine = GeofenceEngine([depot()], hysteresis_m=25)
        engine.update("d", 0, at(90))
        assert engine.update("d", 1, at(120)) == []
        (event,) = engine.update("d", 2, at(130))
        assert event.type is EventType.EXIT
        assert event.duration_s == 2.0

    def test_margin_does_not_widen_entry(self):
        engine = GeofenceEngine([depot()], hysteresis_m=25)
        assert engine.update("d", 0, at(110)) == []
        assert engine.inside("d") == ()

    def test_margin_applies_to_polygons(self):
        square = Fence("sq", Polygon(Ring([(0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0)])))
        engine = GeofenceEngine([square], hysteresis_m=200)
        engine.update("d", 0, (0.005, 0.005))
        # about 111 m north of the top edge: inside the margin
        assert engine.update("d", 1, (0.011, 0.005)) == []
        # about 333 m north: out
        assert kinds(engine.update("d", 2, (0.013, 0.005))) == [("exit", "sq")]


class TestConfirmations:
    def test_enter_needs_consecutive_samples(self):
        engine = GeofenceEngine([depot()], confirmations=3)
        assert engine.update("d", 0, at(0)) == []
        assert engine.update("d", 1, at(0)) == []
        (event,) = engine.update("d", 2, at(10))
        assert event.type is EventType.ENTER
        assert event.timestamp == 2.0
        assert event.point == at(10)

    def test_an_outside_sample_resets_the_enter_streak(self):
        engine = GeofenceEngine([depot()], confirmations=2)
        assert engine.update("d", 0, at(0)) == []
        assert engine.update("d", 1, at(500)) == []
        assert engine.update("d", 2, at(0)) == []
        assert kinds(engine.update("d", 3, at(0))) == [("enter", "depot")]

    def test_exit_needs_consecutive_samples(self):
        engine = GeofenceEngine([depot()], confirmations=2)
        engine.update("d", 0, at(0))
        engine.update("d", 1, at(0))
        assert engine.update("d", 2, at(500)) == []
        assert engine.inside("d") == ("depot",)
        assert engine.update("d", 3, at(0)) == []
        assert engine.update("d", 4, at(500)) == []
        (event,) = engine.update("d", 5, at(500))
        assert event.type is EventType.EXIT
        assert event.duration_s == 4.0

    def test_single_spike_outside_is_ignored(self):
        engine = GeofenceEngine([depot()], confirmations=2)
        seen = []
        for t, offset in enumerate([0, 0, 900, 0, 0]):
            seen.extend(kinds(engine.update("d", t, at(offset))))
        assert seen == [("enter", "depot")]


class TestDwell:
    def test_dwell_fires_once_per_visit(self):
        engine = GeofenceEngine([depot()], dwell_s=60)
        assert kinds(engine.update("d", 0, at(0))) == [("enter", "depot")]
        assert engine.update("d", 59, at(10)) == []
        (event,) = engine.update("d", 75, at(20))
        assert event.type is EventType.DWELL
        assert event.duration_s == 75.0
        assert engine.update("d", 500, at(0)) == []

    def test_dwell_fires_exactly_at_the_threshold(self):
        engine = GeofenceEngine([depot()], dwell_s=60)
        engine.update("d", 0, at(0))
        assert kinds(engine.update("d", 60, at(0))) == [("dwell", "depot")]

    def test_no_dwell_when_the_visit_is_short(self):
        engine = GeofenceEngine([depot()], dwell_s=60)
        engine.update("d", 0, at(0))
        assert kinds(engine.update("d", 30, at(500))) == [("exit", "depot")]
        assert engine.update("d", 100, at(500)) == []

    def test_dwell_restarts_after_reentry(self):
        engine = GeofenceEngine([depot()], dwell_s=10)
        engine.update("d", 0, at(0))
        assert kinds(engine.update("d", 10, at(0))) == [("dwell", "depot")]
        engine.update("d", 20, at(500))
        engine.update("d", 30, at(0))
        assert engine.update("d", 35, at(0)) == []
        assert kinds(engine.update("d", 41, at(0))) == [("dwell", "depot")]

    def test_dwell_counts_time_spent_in_the_exit_margin(self):
        engine = GeofenceEngine([depot()], dwell_s=10, hysteresis_m=50)
        engine.update("d", 0, at(0))
        assert kinds(engine.update("d", 12, at(120))) == [("dwell", "depot")]

    def test_dwell_is_not_emitted_without_the_setting(self):
        engine = GeofenceEngine([depot()])
        engine.update("d", 0, at(0))
        assert engine.update("d", 10_000, at(0)) == []


class TestOrderingAndValidation:
    def test_older_timestamp_raises_and_keeps_state(self):
        engine = GeofenceEngine([depot()])
        engine.update("d", 100, at(0))
        with pytest.raises(OutOfOrderError, match="'d'.*earlier"):
            engine.update("d", 99, at(500))
        assert engine.inside("d") == ("depot",)
        assert engine.last_position("d") == Position("d", 100.0, CENTER)

    def test_equal_timestamps_are_accepted(self):
        engine = GeofenceEngine([depot()])
        engine.update("d", 100, at(0))
        assert kinds(engine.update("d", 100, at(500))) == [("exit", "depot")]

    def test_out_of_order_error_is_a_value_error(self):
        engine = GeofenceEngine()
        engine.update("d", 5, (0, 0))
        with pytest.raises(ValueError):
            engine.update("d", 4, (0, 0))

    @pytest.mark.parametrize("device", ["", "   ", None, 7])
    def test_bad_device_ids(self, device):
        with pytest.raises(ValidationError, match="device id"):
            GeofenceEngine().update(device, 0, (0, 0))

    @pytest.mark.parametrize("timestamp", [None, "12", math.nan, math.inf, True])
    def test_bad_timestamps(self, timestamp):
        with pytest.raises(ValidationError, match="timestamp"):
            GeofenceEngine().update("d", timestamp, (0, 0))

    def test_bad_coordinates(self):
        engine = GeofenceEngine()
        with pytest.raises(InvalidCoordinateError):
            engine.update("d", 0, (95, 0))
        assert engine.devices() == []


class TestFenceManagement:
    def test_added_fence_is_entered_on_the_next_update(self):
        engine = GeofenceEngine()
        assert engine.update("d", 0, at(0)) == []
        engine.add_fence(depot())
        assert kinds(engine.update("d", 1, at(0))) == [("enter", "depot")]

    def test_add_duplicate_fence(self):
        engine = GeofenceEngine([depot()])
        with pytest.raises(DuplicateFenceError):
            engine.add_fence(depot())

    def test_removed_fence_emits_nothing_further(self):
        engine = GeofenceEngine([depot()], confirmations=1)
        engine.update("d", 0, at(0))
        removed = engine.remove_fence("depot")
        assert removed.id == "depot"
        assert engine.inside("d") == ()
        assert engine.update("d", 1, at(500)) == []

    def test_remove_unknown_fence(self):
        with pytest.raises(UnknownFenceError):
            GeofenceEngine().remove_fence("nope")

    def test_occupants_of_unknown_fence(self):
        with pytest.raises(UnknownFenceError):
            GeofenceEngine().occupants("nope")


class TestDeviceState:
    def test_unknown_device(self):
        engine = GeofenceEngine([depot()])
        assert engine.inside("ghost") == ()
        assert engine.last_position("ghost") is None
        assert engine.forget("ghost") is False

    def test_forget_drops_visits_and_ordering(self):
        engine = GeofenceEngine([depot()])
        engine.update("d", 100, at(0))
        assert engine.forget("d") is True
        assert engine.devices() == []
        assert kinds(engine.update("d", 5, at(0))) == [("enter", "depot")]

    def test_last_position_follows_updates(self):
        engine = GeofenceEngine()
        engine.update("d", 1, (10, 20))
        engine.update("d", 2.5, (11, 21))
        assert engine.last_position("d") == Position("d", 2.5, Coordinate(11, 21))


class TestProcess:
    def test_process_yields_events_lazily_in_stream_order(self):
        engine = GeofenceEngine([depot()], dwell_s=30)
        track = [
            Position("a", 0, at(500)),
            Position("b", 0, at(0)),
            Position("a", 10, at(0)),
            Position("b", 40, at(0)),
            Position("a", 50, at(500)),
        ]
        events = list(engine.process(track))
        assert [(e.device_id, e.type.value) for e in events] == [
            ("b", "enter"),
            ("a", "enter"),
            ("b", "dwell"),
            ("a", "exit"),
        ]

    def test_process_stops_at_the_first_out_of_order_fix(self):
        engine = GeofenceEngine([depot()])
        stream = engine.process([Position("a", 10, at(0)), Position("a", 5, at(0))])
        assert next(stream).type is EventType.ENTER
        with pytest.raises(OutOfOrderError):
            next(stream)

    def test_event_to_dict(self):
        event = Event(EventType.EXIT, "truck", "depot", 12.5, Coordinate(1.5, 2.5), 7.0)
        assert event.to_dict() == {
            "type": "exit",
            "device": "truck",
            "fence": "depot",
            "timestamp": 12.5,
            "lat": 1.5,
            "lon": 2.5,
            "duration_s": 7.0,
        }
