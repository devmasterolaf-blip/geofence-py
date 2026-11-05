import pytest

from geofence.coords import Coordinate
from geofence.engine import Position
from geofence.errors import ParseError, TrackParseError
from geofence.track import (
    DEFAULT_DEVICE,
    format_timestamp,
    parse_timestamp,
    parse_track,
    read_track,
    sort_track,
)


def lines(text):
    return text.strip("\n").split("\n")


class TestParseTimestamp:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("0", 0.0),
            ("1700000000", 1700000000.0),
            (" 12.5 ", 12.5),
            ("-3", -3.0),
            ("1970-01-01T00:00:00Z", 0.0),
            ("1970-01-01T00:01:00z", 60.0),
            ("1970-01-01T00:00:00", 0.0),
            ("1970-01-01 00:00:10", 10.0),
            ("1970-01-01T01:00:00+01:00", 0.0),
            ("1970-01-01T00:00:00.250Z", 0.25),
            ("2026-03-01T08:15:00Z", 1772352900.0),
        ],
    )
    def test_accepted_forms(self, text, expected):
        assert parse_timestamp(text) == expected

    @pytest.mark.parametrize("text", ["", "   ", "noon", "nan", "inf", "2026-13-01T00:00:00Z", "12:00"])
    def test_rejected_forms(self, text):
        with pytest.raises(ValueError):
            parse_timestamp(text)


class TestFormatTimestamp:
    def test_whole_seconds(self):
        assert format_timestamp(0) == "1970-01-01T00:00:00Z"
        assert format_timestamp(1772352900) == "2026-03-01T08:15:00Z"

    def test_fractional_seconds_use_milliseconds(self):
        assert format_timestamp(0.25) == "1970-01-01T00:00:00.250Z"

    def test_round_trip(self):
        assert parse_timestamp(format_timestamp(1772352900.5)) == 1772352900.5


class TestParseTrack:
    def test_basic_file(self):
        track = parse_track(
            lines(
                """
device,timestamp,lat,lon
truck-1,10,48.0,11.0
truck-2,2026-03-01T08:15:00Z,-33.9,18.4
"""
            )
        )
        assert track == [
            Position("truck-1", 10.0, Coordinate(48.0, 11.0)),
            Position("truck-2", 1772352900.0, Coordinate(-33.9, 18.4)),
        ]

    def test_header_aliases_order_and_extra_columns(self):
        track = parse_track(
            lines(
                """
 Longitude , speed, LATITUDE, Time, Device_ID
11.5, 30, 48.25, 7, van
"""
            )
        )
        assert track == [Position("van", 7.0, Coordinate(48.25, 11.5))]

    def test_missing_device_column_uses_default(self):
        track = parse_track(["ts,lat,lng", "1,2,3"])
        assert track == [Position(DEFAULT_DEVICE, 1.0, Coordinate(2, 3))]

    def test_blank_lines_are_skipped(self):
        track = parse_track(["", "timestamp,lat,lon", "", "1,2,3", " , , ", "2,2,3", ""])
        assert [p.timestamp for p in track] == [1.0, 2.0]

    def test_quoted_fields(self):
        track = parse_track(['device,timestamp,lat,lon', '"truck, north",5,"1.5","2.5"'])
        assert track == [Position("truck, north", 5.0, Coordinate(1.5, 2.5))]

    def test_header_only_gives_no_positions(self):
        assert parse_track(["timestamp,lat,lon"]) == []

    def test_file_order_is_preserved(self):
        track = parse_track(["timestamp,lat,lon", "5,0,0", "3,0,0", "4,0,0"])
        assert [p.timestamp for p in track] == [5.0, 3.0, 4.0]

    @pytest.mark.parametrize(
        "rows, line, fragment",
        [
            ([], None, "track is empty"),
            (["", "  "], None, "track is empty"),
            (["lat,lon", "1,2"], 1, "missing required column(s): timestamp"),
            (["device,when,y,x"], 1, "missing required column(s): timestamp, lat, lon"),
            (["time,timestamp,lat,lon"], 1, "more than one timestamp column"),
            (["timestamp,lat,lon", "1,2"], 2, "expected at least 3 fields, got 2"),
            (["timestamp,lat,lon", "1,2,3", "soon,2,3"], 3, "neither a number nor an ISO-8601"),
            (["timestamp,lat,lon", "1,north,3"], 2, "latitude is not a number: 'north'"),
            (["timestamp,lat,lon", "1,2,"], 2, "longitude is not a number: ''"),
            (["timestamp,lat,lon", "1,91,3"], 2, "latitude"),
            (["timestamp,lat,lon", "1,2,181"], 2, "longitude"),
            (["timestamp,lat,lon", "", "1,nan,3"], 3, "latitude"),
            (["device,timestamp,lat,lon", " ,1,2,3"], 2, "device id is empty"),
        ],
    )
    def test_errors_carry_the_line_number(self, rows, line, fragment):
        with pytest.raises(TrackParseError) as info:
            parse_track(rows)
        assert info.value.line == line
        assert fragment in str(info.value)
        if line is not None:
            assert str(info.value).startswith(f"line {line}: ")

    def test_track_errors_are_parse_errors(self):
        with pytest.raises(ParseError):
            parse_track([])


class TestReadTrack:
    def test_reads_a_file(self, tmp_path):
        path = tmp_path / "track.csv"
        path.write_text("device,timestamp,lat,lon\r\na,1,2,3\r\nb,2,3,4\r\n", encoding="utf-8")
        assert [p.device_id for p in read_track(path)] == ["a", "b"]

    def test_multiline_quoted_field_keeps_line_numbers_right(self, tmp_path):
        path = tmp_path / "track.csv"
        path.write_text(
            'device,timestamp,lat,lon,note\na,1,2,3,"two\nlines"\nb,bad,3,4,x\n', encoding="utf-8"
        )
        with pytest.raises(TrackParseError) as info:
            read_track(path)
        assert info.value.line == 4

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_track(tmp_path / "nope.csv")


class TestSortTrack:
    def test_sorts_by_time_and_is_stable(self):
        track = [
            Position("a", 5, Coordinate(0, 0)),
            Position("b", 1, Coordinate(0, 0)),
            Position("c", 5, Coordinate(1, 1)),
            Position("d", 3, Coordinate(0, 0)),
        ]
        assert [p.device_id for p in sort_track(track)] == ["b", "d", "a", "c"]
