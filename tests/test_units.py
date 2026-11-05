import math

import pytest

from geofence import units
from geofence.errors import UnitError, ValidationError


@pytest.mark.parametrize(
    "value, unit, expected",
    [
        (1, "m", 1.0),
        (2.5, "km", 2500.0),
        (1, "mi", 1609.344),
        (1, "nmi", 1852.0),
        (10, "ft", 3.048),
    ],
)
def test_to_meters(value, unit, expected):
    assert units.to_meters(value, unit) == pytest.approx(expected)


def test_from_meters_round_trip():
    for unit in units.METERS_PER_UNIT:
        assert units.from_meters(units.to_meters(12.5, unit), unit) == pytest.approx(12.5)


def test_convert_between_units():
    assert units.convert(26.2, "mi", "km") == pytest.approx(42.1648128)
    assert units.convert(1, "nmi", "ft") == pytest.approx(6076.1155, rel=1e-7)


@pytest.mark.parametrize(
    "alias, canonical",
    [
        ("KM", "km"),
        (" Miles ", "mi"),
        ("nm", "nmi"),
        ("nautical miles", "nmi"),
        ("nautical-mile", "nmi"),
        ("metres", "m"),
        ("feet", "ft"),
    ],
)
def test_aliases(alias, canonical):
    assert units.canonical_unit(alias) == canonical


def test_unknown_unit_lists_known_ones():
    with pytest.raises(UnitError) as info:
        units.to_meters(1, "furlong")
    assert "furlong" in str(info.value)
    assert "km" in str(info.value)


def test_non_string_unit_rejected():
    with pytest.raises(UnitError):
        units.canonical_unit(5)


@pytest.mark.parametrize("bad", [math.nan, math.inf, "12", None, True])
def test_non_finite_or_non_numeric_length_rejected(bad):
    with pytest.raises(ValidationError):
        units.to_meters(bad, "m")


def test_format_distance():
    assert units.format_distance(1500, "km") == "1.500 km"
    assert units.format_distance(1852, "nautical_miles", precision=1) == "1.0 nmi"
    assert units.format_distance(12.3456) == "12.346 m"
    with pytest.raises(ValidationError):
        units.format_distance(1, "m", precision=-1)
