import math
import random

import pytest

from geofence.bbox import BoundingBox
from geofence.circle import Circle
from geofence.errors import DuplicateFenceError, UnknownFenceError, ValidationError
from geofence.fence import Fence
from geofence.index import FenceIndex, GridIndex
from geofence.polygon import Polygon


def square(lat, lon, size=1.0):
    return Polygon([(lat, lon), (lat, lon + size), (lat + size, lon + size), (lat + size, lon)])


class TestGridIndex:
    def test_insert_query_remove(self):
        grid = GridIndex(1.0)
        grid.insert("a", BoundingBox(0, 0, 2, 2))
        grid.insert("b", BoundingBox(1, 1, 3, 3))
        assert len(grid) == 2 and "a" in grid
        assert grid.query_point((0.5, 0.5)) == {"a"}
        assert grid.query_point((1.5, 1.5)) == {"a", "b"}
        assert grid.query_point((5, 5)) == set()
        grid.remove("a")
        assert grid.query_point((1.5, 1.5)) == {"b"}
        assert "a" not in grid
        with pytest.raises(KeyError):
            grid.remove("a")

    def test_reinsert_replaces_the_box(self):
        grid = GridIndex(1.0)
        grid.insert("a", BoundingBox(0, 0, 1, 1))
        grid.insert("a", BoundingBox(10, 10, 11, 11))
        assert len(grid) == 1
        assert grid.query_point((0.5, 0.5)) == set()
        assert grid.query_point((10.5, 10.5)) == {"a"}

    def test_only_exact_box_hits_are_returned(self):
        grid = GridIndex(10.0)
        grid.insert("small", BoundingBox(1, 1, 2, 2))
        assert grid.query_point((5, 5)) == set()  # same cell, outside the box

    def test_query_box(self):
        grid = GridIndex(1.0)
        grid.insert("a", BoundingBox(0, 0, 2, 2))
        grid.insert("b", BoundingBox(5, 5, 6, 6))
        assert grid.query_box(BoundingBox(1, 1, 5, 5)) == {"a", "b"}
        assert grid.query_box(BoundingBox(3, 3, 4, 4)) == set()
        assert grid.query_box(BoundingBox.world()) == {"a", "b"}

    def test_box_crossing_antimeridian(self):
        grid = GridIndex(1.0)
        grid.insert("x", BoundingBox(-1, 179, 1, -179))
        assert grid.query_point((0, 179.5)) == {"x"}
        assert grid.query_point((0, -179.5)) == {"x"}
        assert grid.query_point((0, 180)) == {"x"}
        assert grid.query_point((0, -180)) == {"x"}
        assert grid.query_point((0, 0)) == set()
        assert grid.query_box(BoundingBox(0, -179.5, 0.5, -170)) == {"x"}

    def test_both_spellings_of_the_antimeridian_find_boxes_ending_there(self):
        grid = GridIndex(1.0)
        grid.insert("east", BoundingBox(0, 170, 1, 180))
        grid.insert("west", BoundingBox(0, -180, 1, -170))
        assert grid.query_point((0.5, 180)) == {"east", "west"}
        assert grid.query_point((0.5, -180)) == {"east", "west"}

    def test_oversized_entries_are_still_found(self):
        grid = GridIndex(0.5, max_cells_per_item=16)
        grid.insert("huge", BoundingBox(-60, -100, 60, 100))
        grid.insert("tiny", BoundingBox(0, 0, 0.1, 0.1))
        assert grid.query_point((30, 50)) == {"huge"}
        assert grid.query_point((0.05, 0.05)) == {"huge", "tiny"}
        assert grid.query_box(BoundingBox(59, 99, 61, 101)) == {"huge"}
        grid.remove("huge")
        assert grid.query_point((30, 50)) == set()

    def test_poles_and_cell_size_that_does_not_divide_evenly(self):
        grid = GridIndex(7.0)
        grid.insert("north", BoundingBox(85, -180, 90, 180))
        assert grid.query_point((90, 0)) == {"north"}
        assert grid.query_point((87, 179.9)) == {"north"}
        assert grid.query_point((84, 0)) == set()

    @pytest.mark.parametrize("size", [0, -1, 91, math.nan, "1", True])
    def test_bad_cell_size(self, size):
        with pytest.raises(ValidationError):
            GridIndex(size)

    def test_bad_arguments(self):
        with pytest.raises(ValidationError):
            GridIndex(1.0, max_cells_per_item=0)
        with pytest.raises(ValidationError):
            GridIndex(1.0).insert("a", (0, 0, 1, 1))
        with pytest.raises(ValidationError):
            GridIndex(1.0).query_box("box")

    def test_matches_brute_force_on_random_boxes(self):
        rng = random.Random(7)
        grid = GridIndex(2.5)
        boxes = {}
        for key in range(200):
            south = rng.uniform(-80, 70)
            west = rng.uniform(-180, 180)
            east = west + rng.uniform(0.1, 30)
            if east > 180:
                east -= 360
            boxes[key] = BoundingBox(south, west, south + rng.uniform(0.1, 10), east)
            grid.insert(key, boxes[key])
        for _ in range(300):
            point = (rng.uniform(-90, 90), rng.uniform(-180, 180))
            expected = {key for key, box in boxes.items() if box.contains(point)}
            assert grid.query_point(point) == expected
        for _ in range(50):
            probe = boxes[rng.randrange(200)].expand(rng.uniform(0, 200_000))
            expected = {key for key, box in boxes.items() if box.intersects(probe)}
            assert grid.query_box(probe) == expected


class TestFenceIndex:
    def make(self):
        return FenceIndex(
            [
                Fence("b-square", square(0, 0)),
                Fence("a-square", square(0.5, 0.5)),
                Fence("circle", Circle((10, 10), 20_000)),
            ]
        )

    def test_len_iter_contains_get(self):
        index = self.make()
        assert len(index) == 3
        assert [fence.id for fence in index] == ["a-square", "b-square", "circle"]
        assert "circle" in index and "nope" not in index
        assert index.get("circle").id == "circle"

    def test_duplicate_and_unknown_ids(self):
        index = self.make()
        with pytest.raises(DuplicateFenceError, match="b-square"):
            index.add(Fence("b-square", square(40, 40)))
        with pytest.raises(UnknownFenceError, match="nope"):
            index.get("nope")
        with pytest.raises(UnknownFenceError):
            index.remove("nope")
        with pytest.raises(ValidationError):
            index.add("not a fence")

    def test_containing_returns_fences_in_id_order(self):
        index = self.make()
        assert [f.id for f in index.containing((0.75, 0.75))] == ["a-square", "b-square"]
        assert [f.id for f in index.containing((0.25, 0.25))] == ["b-square"]
        assert [f.id for f in index.containing((10.05, 10.05))] == ["circle"]
        assert index.containing((50, 50)) == []

    def test_containing_checks_the_shape_not_just_the_box(self):
        index = self.make()
        # Inside the circle's bounding box but outside the circle itself.
        corner = (10.17, 10.17)
        assert index.get("circle").bbox.contains(corner)
        assert index.containing(corner) == []

    def test_boundary_flag(self):
        index = self.make()
        assert [f.id for f in index.containing((0, 0.25))] == ["b-square"]
        assert index.containing((0, 0.25), boundary=False) == []

    def test_remove(self):
        index = self.make()
        removed = index.remove("a-square")
        assert removed.id == "a-square"
        assert [f.id for f in index.containing((0.75, 0.75))] == ["b-square"]
        assert len(index) == 2

    def test_intersecting(self):
        index = self.make()
        assert [f.id for f in index.intersecting(BoundingBox(0.9, 0.9, 1.2, 1.2))] == [
            "a-square",
            "b-square",
        ]
        assert index.intersecting(BoundingBox(30, 30, 31, 31)) == []
