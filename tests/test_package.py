import re

import geofence


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+", geofence.__version__)
