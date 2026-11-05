import importlib
import re

import geofence
from geofence import errors


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+", geofence.__version__)


def test_all_names_resolve_and_are_sorted_uniquely():
    assert len(set(geofence.__all__)) == len(geofence.__all__)
    for name in geofence.__all__:
        assert hasattr(geofence, name), name


def test_every_error_class_is_exported():
    declared = {
        name
        for name, value in vars(errors).items()
        if isinstance(value, type) and issubclass(value, errors.GeofenceError)
    }
    assert declared <= set(geofence.__all__)


def test_star_import_exposes_the_main_types():
    namespace = {}
    exec("from geofence import *", namespace)
    for name in ("Coordinate", "Polygon", "Fence", "GeofenceEngine", "distance", "wkt"):
        assert name in namespace


def test_top_level_functions_are_the_module_functions():
    assert geofence.distance is geofence.geodesy.distance
    assert geofence.Coordinate is importlib.import_module("geofence.coords").Coordinate


def test_quick_tour():
    berlin = geofence.Coordinate(52.52, 13.405)
    fence = geofence.Fence("mitte", geofence.Circle(berlin, 2_000))
    engine = geofence.GeofenceEngine([fence])
    assert [e.type for e in engine.update("bike", 0, berlin)] == [geofence.EventType.ENTER]
    far = geofence.destination(berlin, 90, 5_000)
    assert [e.type for e in engine.update("bike", 60, far)] == [geofence.EventType.EXIT]
