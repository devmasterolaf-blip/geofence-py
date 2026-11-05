"""The files under examples/ are quoted in the README; keep them working."""

import runpy
from pathlib import Path

import pytest

from geofence.cli import EXIT_OK, main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run(capsys, *argv):
    code = main([str(arg) for arg in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_events_example(capsys):
    code, out, err = run(
        capsys, "events", EXAMPLES / "fences.geojson", EXAMPLES / "track.csv",
        "--dwell", "180", "--hysteresis", "20",
    )
    assert code == EXIT_OK
    assert out.splitlines() == [
        "2026-03-01T08:01:00Z\ttruck-1\tenter\tdepot",
        "2026-03-01T08:02:00Z\ttruck-2\tenter\tgate",
        "2026-03-01T08:05:00Z\ttruck-1\tdwell\tdepot\t240s",
        "2026-03-01T08:07:00Z\ttruck-1\texit\tdepot\t360s",
        "2026-03-01T08:07:00Z\ttruck-1\tenter\tgate",
        "2026-03-01T08:08:00Z\ttruck-2\texit\tgate\t360s",
        "2026-03-01T08:09:00Z\ttruck-1\texit\tgate\t120s",
    ]
    assert err == "7 event(s) from 8 position(s), 2 device(s), 2 fence(s)\n"


def test_example_fences_pass_strict_loading(capsys):
    code, out, _ = run(capsys, "contains", EXAMPLES / "fences.geojson", "48.005,11.005", "--strict")
    assert code == EXIT_OK
    assert out == "depot\tMain depot\n"


def test_simplify_example(capsys):
    code, out, err = run(capsys, "simplify", EXAMPLES / "route.wkt", "--tolerance", "20000")
    assert code == EXIT_OK
    assert out == "LINESTRING (13.405 52.52, 12.9 52.39, 11.9 50.9, 11.582 48.1351)\n"
    assert err == "6 -> 4 points\n"


def test_quickstart_script(capsys):
    runpy.run_path(str(EXAMPLES / "quickstart.py"), run_name="__main__")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Berlin -> Munich: 504.7 km"
    assert lines[1] == "Geohash of Berlin: u33dc0c"
    assert lines[2] == "Fences containing Marienplatz: ['Munich old town']"
    assert lines[3] == "Nearest fence to Berlin: Munich old town (504 km)"
    assert [line.split("s ", 1)[1].split()[:2] for line in lines[4:]] == [
        ["enter", "station"],
        ["dwell", "station"],
        ["exit", "station"],
        ["enter", "old-town"],
        ["exit", "old-town"],
    ]


@pytest.mark.parametrize("name", ["fences.geojson", "track.csv", "route.wkt", "quickstart.py"])
def test_example_files_exist(name):
    assert (EXAMPLES / name).is_file()
