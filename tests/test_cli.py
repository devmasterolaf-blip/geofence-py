import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import geofence
from geofence.cli import EXIT_DATA, EXIT_IO, EXIT_NO_MATCH, EXIT_OK, EXIT_USAGE, main

FENCES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": "depot",
            "properties": {"name": "Main depot"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[11.0, 48.0], [11.01, 48.0], [11.01, 48.01], [11.0, 48.01], [11.0, 48.0]]
                ],
            },
        },
        {
            "type": "Feature",
            "id": "gate",
            "properties": {"radius_m": 150},
            "geometry": {"type": "Point", "coordinates": [11.02, 48.005]},
        },
    ],
}

TRACK = """device,timestamp,lat,lon
truck,2026-03-01T08:00:00Z,48.005,10.99
truck,2026-03-01T08:01:00Z,48.005,11.005
truck,2026-03-01T08:05:00Z,48.006,11.006
truck,2026-03-01T08:06:00Z,48.005,11.0101
truck,2026-03-01T08:07:00Z,48.005,11.02
truck,2026-03-01T08:09:00Z,48.005,11.03
"""


@pytest.fixture
def fences_file(tmp_path):
    path = tmp_path / "fences.geojson"
    path.write_text(json.dumps(FENCES), encoding="utf-8")
    return str(path)


@pytest.fixture
def track_file(tmp_path):
    path = tmp_path / "track.csv"
    path.write_text(TRACK, encoding="utf-8")
    return str(path)


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestGeneral:
    def test_version(self, capsys):
        code, out, _ = run(capsys, "--version")
        assert code == EXIT_OK
        assert out.strip() == f"geofence {geofence.__version__}"

    def test_help_lists_every_command(self, capsys):
        code, out, _ = run(capsys, "--help")
        assert code == EXIT_OK
        for command in ("distance", "contains", "simplify", "geohash", "events"):
            assert command in out

    def test_no_command_is_a_usage_error(self, capsys):
        code, out, err = run(capsys)
        assert code == EXIT_USAGE
        assert out == ""
        assert "usage:" in err

    def test_unknown_command(self, capsys):
        code, _, err = run(capsys, "teleport")
        assert code == EXIT_USAGE
        assert "invalid choice" in err

    def test_unknown_option(self, capsys):
        code, _, err = run(capsys, "distance", "0,0", "1,1", "--warp")
        assert code == EXIT_USAGE
        assert "--warp" in err


class TestDistance:
    def test_default_output_is_metres(self, capsys):
        code, out, _ = run(capsys, "distance", "0,0", "0,1", "--method", "haversine")
        assert code == EXIT_OK
        assert out == "111195.080 m\n"

    def test_unit_precision_and_method(self, capsys):
        code, out, _ = run(
            capsys, "distance", "52.52,13.405", "48.8566,2.3522",
            "--unit", "km", "--precision", "1", "--method", "vincenty",
        )
        assert code == EXIT_OK
        assert out == "879.7 km\n"

    def test_negative_coordinates_are_not_taken_for_options(self, capsys):
        code, out, _ = run(
            capsys, "distance", "-33.9249,18.4241", "-34.6037,-58.3816", "--unit", "km", "--precision", "0"
        )
        assert code == EXIT_OK
        assert 6800 < float(out.split()[0]) < 7000

    def test_leading_dot_negative_coordinate(self, capsys):
        code, out, _ = run(capsys, "distance", "-.5,0", ".5,0", "--method", "haversine", "--precision", "0")
        assert code == EXIT_OK
        assert out == "111195 m\n"

    def test_bearing(self, capsys):
        code, out, _ = run(capsys, "distance", "0,0", "0,1", "--bearing")
        assert code == EXIT_OK
        assert out.splitlines()[1] == "initial bearing 90.000 deg"

    def test_bearing_of_identical_points(self, capsys):
        code, out, _ = run(capsys, "distance", "5,5", "5,5", "--bearing")
        assert code == EXIT_OK
        assert out.splitlines() == ["0.000 m", "initial bearing undefined (same point)"]

    @pytest.mark.parametrize("bad", ["91,0", "abc", "1;2", "1,2,3", "nan,0"])
    def test_malformed_point_is_a_usage_error(self, capsys, bad):
        code, out, err = run(capsys, "distance", bad, "0,0")
        assert code == EXIT_USAGE
        assert out == ""
        assert "error: argument LAT,LON" in err

    def test_unknown_unit(self, capsys):
        code, _, err = run(capsys, "distance", "0,0", "1,1", "--unit", "parsec")
        assert code == EXIT_USAGE
        assert "parsec" in err


class TestContains:
    def test_lists_matching_fences(self, capsys, fences_file):
        code, out, _ = run(capsys, "contains", fences_file, "48.005,11.005")
        assert code == EXIT_OK
        assert out == "depot\tMain depot\n"

    def test_circle_fence(self, capsys, fences_file):
        code, out, _ = run(capsys, "contains", fences_file, "48.0051,11.0201")
        assert code == EXIT_OK
        assert out == "gate\tgate\n"

    def test_no_match_exits_one_silently(self, capsys, fences_file):
        code, out, err = run(capsys, "contains", fences_file, "0,0")
        assert code == EXIT_NO_MATCH
        assert out == "" and err == ""

    def test_boundary_can_be_excluded(self, capsys, fences_file):
        assert run(capsys, "contains", fences_file, "48.0,11.005")[0] == EXIT_OK
        code, out, _ = run(capsys, "contains", fences_file, "48.0,11.005", "--exclude-boundary")
        assert code == EXIT_NO_MATCH
        assert out == ""

    def test_missing_file(self, capsys, tmp_path):
        code, out, err = run(capsys, "contains", str(tmp_path / "nope.geojson"), "0,0")
        assert code == EXIT_IO
        assert out == ""
        assert "nope.geojson" in err and "No such file" in err

    def test_invalid_geojson_reports_the_path(self, capsys, tmp_path):
        path = tmp_path / "bad.geojson"
        path.write_text('{"type": "FeatureCollection", "features": [{"type": "Feature"}]}')
        code, _, err = run(capsys, "contains", str(path), "0,0")
        assert code == EXIT_DATA
        assert err.startswith("geofence: error: $.features[0].geometry: ")

    def test_non_utf8_file(self, capsys, tmp_path):
        path = tmp_path / "latin.geojson"
        path.write_bytes(b'{"name": "caf\xe9"}')
        code, _, err = run(capsys, "contains", str(path), "0,0")
        assert code == EXIT_DATA
        assert "not valid UTF-8" in err


class TestSimplify:
    def feed(self, monkeypatch, text):
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))

    def test_wkt_from_stdin(self, capsys, monkeypatch):
        self.feed(monkeypatch, "LINESTRING (0 0, 1 0.001, 2 0, 3 1)\n")
        code, out, err = run(capsys, "simplify", "-", "--tolerance", "500")
        assert code == EXIT_OK
        assert out == "LINESTRING (0 0, 2 0, 3 1)\n"
        assert err == "4 -> 3 points\n"

    def test_zero_tolerance_keeps_everything(self, capsys, monkeypatch):
        self.feed(monkeypatch, "LINESTRING (0 0, 1 0.001, 2 0)")
        code, out, _ = run(capsys, "simplify", "-", "--tolerance", "0")
        assert code == EXIT_OK
        assert out == "LINESTRING (0 0, 1 0.001, 2 0)\n"

    def test_geojson_file_keeps_its_format(self, capsys, tmp_path):
        path = tmp_path / "line.geojson"
        path.write_text(
            json.dumps({"type": "LineString", "coordinates": [[0, 0], [1, 0.001], [2, 0]]})
        )
        code, out, _ = run(capsys, "simplify", str(path), "--tolerance", "500")
        assert code == EXIT_OK
        assert json.loads(out) == {"type": "LineString", "coordinates": [[0.0, 0.0], [2.0, 0.0]]}

    def test_geojson_feature_input_and_wkt_output(self, capsys, monkeypatch):
        feature = {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0.001], [2, 0]]},
        }
        self.feed(monkeypatch, json.dumps(feature))
        code, out, _ = run(capsys, "simplify", "-", "--tolerance", "500", "--format", "wkt")
        assert code == EXIT_OK
        assert out == "LINESTRING (0 0, 2 0)\n"

    def test_wkt_precision(self, capsys, monkeypatch):
        self.feed(monkeypatch, "LINESTRING (0.123456789 0, 1 1)")
        _, out, _ = run(capsys, "simplify", "-", "--tolerance", "1", "--precision", "3")
        assert out == "LINESTRING (0.123 0, 1 1)\n"

    def test_tolerance_is_required(self, capsys):
        code, _, err = run(capsys, "simplify", "-")
        assert code == EXIT_USAGE
        assert "--tolerance" in err

    def test_negative_tolerance(self, capsys):
        code, _, err = run(capsys, "simplify", "-", "--tolerance", "-5")
        assert code == EXIT_USAGE
        assert "finite number >= 0" in err

    def test_wkt_syntax_error_reports_the_offset(self, capsys, monkeypatch):
        self.feed(monkeypatch, "LINESTRING (0 0, 1)")
        code, out, err = run(capsys, "simplify", "-", "--tolerance", "1")
        assert code == EXIT_DATA
        assert out == ""
        assert "at offset" in err

    def test_polygon_input_is_rejected(self, capsys, monkeypatch):
        self.feed(monkeypatch, "POLYGON ((0 0, 1 0, 1 1, 0 0))")
        code, _, err = run(capsys, "simplify", "-", "--tolerance", "1")
        assert code == EXIT_DATA
        assert "expected a LINESTRING" in err

    def test_geojson_point_is_rejected(self, capsys, monkeypatch):
        self.feed(monkeypatch, '{"type": "Point", "coordinates": [0, 0]}')
        code, _, err = run(capsys, "simplify", "-", "--tolerance", "1")
        assert code == EXIT_DATA
        assert "$.type: expected a LineString" in err


class TestGeohash:
    def test_encode(self, capsys):
        code, out, _ = run(capsys, "geohash", "encode", "57.64911,10.40744", "--precision", "11")
        assert code == EXIT_OK
        assert out == "u4pruydqqvj\n"

    def test_encode_southern_western_point(self, capsys):
        code, out, _ = run(capsys, "geohash", "encode", "-25.382708,-49.265506", "--precision", "8")
        assert code == EXIT_OK
        assert out == "6gkzwgjz\n"

    def test_decode(self, capsys):
        code, out, _ = run(capsys, "geohash", "decode", "u4pru")
        assert code == EXIT_OK
        lines = dict(line.split(" ") for line in out.splitlines())
        assert set(lines) == {"center", "south", "west", "north", "east"}
        assert float(lines["south"]) < 57.64911 < float(lines["north"])
        assert float(lines["west"]) < 10.40744 < float(lines["east"])

    def test_decode_invalid_hash(self, capsys):
        code, out, err = run(capsys, "geohash", "decode", "abc!")
        assert code == EXIT_DATA
        assert out == ""
        assert err == "geofence: error: invalid geohash character 'a' at position 0 in 'abc!'\n"

    def test_neighbors(self, capsys):
        code, out, _ = run(capsys, "geohash", "neighbors", "u4pru")
        assert code == EXIT_OK
        cells = dict(line.split("\t") for line in out.splitlines())
        assert cells["n"] == "u4r2h" and cells["sw"] == "u4pre"
        assert len(cells) == 8

    def test_cover(self, capsys):
        code, out, _ = run(capsys, "geohash", "cover", "48,11,48.05,11.1", "--precision", "5")
        assert code == EXIT_OK
        assert out.split() == ["u0xc4", "u0xc5", "u0xc6", "u0xc7", "u0xch", "u0xck"]

    def test_cover_with_negative_south(self, capsys):
        code, out, _ = run(capsys, "geohash", "cover", "-0.1,-0.1,0.1,0.1", "--precision", "1")
        assert code == EXIT_OK
        assert out.split() == ["7", "e", "k", "s"]

    def test_cover_limit(self, capsys):
        code, _, err = run(capsys, "geohash", "cover", "0,0,10,10", "--precision", "6", "--max-cells", "10")
        assert code == EXIT_DATA
        assert "more than max_cells=10" in err

    def test_cover_bad_box(self, capsys):
        code, _, err = run(capsys, "geohash", "cover", "1,2,3")
        assert code == EXIT_USAGE
        assert "south,west,north,east" in err

    def test_missing_action(self, capsys):
        code, _, _ = run(capsys, "geohash")
        assert code == EXIT_USAGE


class TestEvents:
    def test_text_output(self, capsys, fences_file, track_file):
        code, out, err = run(capsys, "events", fences_file, track_file)
        assert code == EXIT_OK
        assert out.splitlines() == [
            "2026-03-01T08:01:00Z\ttruck\tenter\tdepot",
            "2026-03-01T08:06:00Z\ttruck\texit\tdepot\t300s",
            "2026-03-01T08:07:00Z\ttruck\tenter\tgate",
            "2026-03-01T08:09:00Z\ttruck\texit\tgate\t120s",
        ]
        assert err == "4 event(s) from 6 position(s), 1 device(s), 2 fence(s)\n"

    def test_hysteresis_and_dwell_options(self, capsys, fences_file, track_file):
        code, out, _ = run(
            capsys, "events", fences_file, track_file, "--hysteresis", "20", "--dwell", "120"
        )
        assert code == EXIT_OK
        assert [line.split("\t")[2:] for line in out.splitlines()] == [
            ["enter", "depot"],
            ["dwell", "depot", "240s"],
            ["exit", "depot", "360s"],
            ["enter", "gate"],
            ["exit", "gate", "120s"],
        ]

    def test_confirm_option(self, capsys, fences_file, track_file):
        code, out, _ = run(capsys, "events", fences_file, track_file, "--confirm", "2")
        assert code == EXIT_OK
        assert [line.split("\t")[2:4] for line in out.splitlines()] == [
            ["enter", "depot"],
            ["exit", "depot"],
        ]

    def test_json_lines(self, capsys, fences_file, track_file):
        code, out, _ = run(capsys, "events", fences_file, track_file, "--format", "json")
        assert code == EXIT_OK
        events = [json.loads(line) for line in out.splitlines()]
        assert [e["type"] for e in events] == ["enter", "exit", "enter", "exit"]
        assert events[1] == {
            "type": "exit",
            "device": "truck",
            "fence": "depot",
            "timestamp": 1772352360.0,
            "lat": 48.005,
            "lon": 11.0101,
            "duration_s": 300.0,
        }

    def test_out_of_order_track_suggests_sort(self, capsys, fences_file, tmp_path):
        lines = TRACK.splitlines()
        shuffled = tmp_path / "shuffled.csv"
        shuffled.write_text("\n".join([lines[0], lines[2], lines[1]] + lines[3:]) + "\n")
        code, _, err = run(capsys, "events", fences_file, str(shuffled))
        assert code == EXIT_DATA
        assert "earlier than the previous update" in err
        assert "--sort" in err

    def test_sort_option_repairs_the_order(self, capsys, fences_file, tmp_path):
        lines = TRACK.splitlines()
        shuffled = tmp_path / "shuffled.csv"
        shuffled.write_text("\n".join([lines[0], lines[2], lines[1]] + lines[3:]) + "\n")
        code, out, _ = run(capsys, "events", fences_file, str(shuffled), "--sort")
        assert code == EXIT_OK
        assert len(out.splitlines()) == 4

    def test_bad_track_row_reports_the_line(self, capsys, fences_file, tmp_path):
        track = tmp_path / "bad.csv"
        track.write_text("device,timestamp,lat,lon\ntruck,1,48,11\ntruck,2,north,11\n")
        code, out, err = run(capsys, "events", fences_file, str(track))
        assert code == EXIT_DATA
        assert out == ""
        assert err == "geofence: error: line 3: latitude is not a number: 'north'\n"

    def test_missing_track_file(self, capsys, fences_file, tmp_path):
        code, _, err = run(capsys, "events", fences_file, str(tmp_path / "gone.csv"))
        assert code == EXIT_IO
        assert "gone.csv" in err

    def test_directory_instead_of_file(self, capsys, fences_file, tmp_path):
        code, _, _ = run(capsys, "events", fences_file, str(tmp_path))
        assert code == EXIT_IO

    @pytest.mark.parametrize(
        "option, value",
        [("--hysteresis", "-1"), ("--dwell", "0"), ("--confirm", "0"), ("--confirm", "1.5")],
    )
    def test_bad_option_values(self, capsys, fences_file, track_file, option, value):
        code, _, err = run(capsys, "events", fences_file, track_file, option, value)
        assert code == EXIT_USAGE
        assert option in err


class TestModuleEntryPoint:
    def test_python_dash_m(self, fences_file):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(geofence.__file__).resolve().parent.parent)
        result = subprocess.run(
            [sys.executable, "-m", "geofence", "contains", fences_file, "0,0"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == EXIT_NO_MATCH
        assert result.stdout == ""
