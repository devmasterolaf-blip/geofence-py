"""Spatial indexing for many fences.

:class:`GridIndex` is a uniform latitude/longitude grid that maps keys to
bounding boxes.  :class:`FenceIndex` builds on it to answer "which fences
contain this point" and nearest-fence queries without testing every fence.
"""

from __future__ import annotations

import math
from typing import Hashable, Iterable, Iterator

from .bbox import BoundingBox
from .coords import CoordinateLike, as_coordinate
from .errors import DuplicateFenceError, UnknownFenceError, ValidationError
from .fence import Fence


class GridIndex:
    """Uniform grid over the globe holding ``key -> bounding box`` entries.

    Each box is registered in every grid cell it touches.  Boxes that would
    touch more than ``max_cells_per_item`` cells are kept in a separate list
    that every query scans, so one continent-sized entry cannot bloat the
    grid.
    """

    def __init__(self, cell_size_deg: float = 0.25, max_cells_per_item: int = 1024) -> None:
        if isinstance(cell_size_deg, bool) or not isinstance(cell_size_deg, (int, float)):
            raise ValidationError(f"cell size must be a real number, got {cell_size_deg!r}")
        if not math.isfinite(cell_size_deg) or not 0.0 < cell_size_deg <= 90.0:
            raise ValidationError(
                f"cell size must be greater than 0 and at most 90 degrees, got {cell_size_deg!r}"
            )
        if (
            isinstance(max_cells_per_item, bool)
            or not isinstance(max_cells_per_item, int)
            or max_cells_per_item < 1
        ):
            raise ValidationError(
                f"max_cells_per_item must be a positive integer, got {max_cells_per_item!r}"
            )
        self._size = float(cell_size_deg)
        self._rows = math.ceil(180.0 / self._size)
        self._cols = math.ceil(360.0 / self._size)
        self._max_cells = max_cells_per_item
        self._cells: dict[tuple[int, int], set[Hashable]] = {}
        self._boxes: dict[Hashable, BoundingBox] = {}
        self._item_cells: dict[Hashable, list[tuple[int, int]]] = {}
        self._large: set[Hashable] = set()

    @property
    def cell_size_deg(self) -> float:
        return self._size

    def __len__(self) -> int:
        return len(self._boxes)

    def __contains__(self, key: object) -> bool:
        return key in self._boxes

    def _row(self, lat: float) -> int:
        return min(int((lat + 90.0) / self._size), self._rows - 1)

    def _col(self, lon: float) -> int:
        return min(int((lon + 180.0) / self._size), self._cols - 1)

    def _cells_for_box(self, box: BoundingBox) -> list[tuple[int, int]] | None:
        """Grid cells touched by a box, or ``None`` when there are too many."""
        row_lo, row_hi = self._row(box.south), self._row(box.north)
        cols: set[int] = set()
        for part in box.split():
            col_lo, col_hi = self._col(part.west), self._col(part.east)
            if (row_hi - row_lo + 1) * (len(cols) + col_hi - col_lo + 1) > self._max_cells:
                return None
            cols.update(range(col_lo, col_hi + 1))
            # Longitudes -180 and 180 are the same meridian: a box that
            # reaches one end of the grid also touches the other end.
            if part.west == -180.0:
                cols.add(self._cols - 1)
            if part.east == 180.0:
                cols.add(0)
        return [(row, col) for row in range(row_lo, row_hi + 1) for col in sorted(cols)]

    def insert(self, key: Hashable, box: BoundingBox) -> None:
        """Add an entry, replacing any existing entry with the same key."""
        if not isinstance(box, BoundingBox):
            raise ValidationError(f"expected a BoundingBox, got {type(box).__name__}")
        if key in self._boxes:
            self.remove(key)
        self._boxes[key] = box
        cells = self._cells_for_box(box)
        if cells is None:
            self._large.add(key)
            return
        self._item_cells[key] = cells
        for cell in cells:
            self._cells.setdefault(cell, set()).add(key)

    def remove(self, key: Hashable) -> None:
        """Remove an entry; raises ``KeyError`` when the key is not present."""
        del self._boxes[key]
        self._large.discard(key)
        for cell in self._item_cells.pop(key, ()):
            members = self._cells[cell]
            members.discard(key)
            if not members:
                del self._cells[cell]

    def query_point(self, point: CoordinateLike) -> set[Hashable]:
        """Keys whose box contains the point."""
        c = as_coordinate(point)
        cells = self._cells_for_box(BoundingBox(c.lat, c.lon, c.lat, c.lon)) or []
        candidates = set(self._large)
        for cell in cells:
            candidates.update(self._cells.get(cell, ()))
        return {key for key in candidates if self._boxes[key].contains(c)}

    def query_box(self, box: BoundingBox) -> set[Hashable]:
        """Keys whose box intersects ``box`` (touching counts)."""
        if not isinstance(box, BoundingBox):
            raise ValidationError(f"expected a BoundingBox, got {type(box).__name__}")
        cells = self._cells_for_box(box)
        if cells is None:
            candidates: Iterable[Hashable] = self._boxes
        else:
            found = set(self._large)
            for cell in cells:
                found.update(self._cells.get(cell, ()))
            candidates = found
        return {key for key in candidates if self._boxes[key].intersects(box)}


class FenceIndex:
    """A set of fences with fast point and box lookups."""

    def __init__(self, fences: Iterable[Fence] = (), cell_size_deg: float = 0.25) -> None:
        self._grid = GridIndex(cell_size_deg)
        self._fences: dict[str, Fence] = {}
        for fence in fences:
            self.add(fence)

    def __len__(self) -> int:
        return len(self._fences)

    def __contains__(self, fence_id: object) -> bool:
        return fence_id in self._fences

    def __iter__(self) -> Iterator[Fence]:
        """Fences in id order."""
        return iter(sorted(self._fences.values(), key=lambda fence: fence.id))

    def add(self, fence: Fence) -> None:
        if not isinstance(fence, Fence):
            raise ValidationError(f"expected a Fence, got {type(fence).__name__}")
        if fence.id in self._fences:
            raise DuplicateFenceError(f"a fence with id {fence.id!r} is already registered")
        self._fences[fence.id] = fence
        self._grid.insert(fence.id, fence.bbox)

    def get(self, fence_id: str) -> Fence:
        try:
            return self._fences[fence_id]
        except KeyError:
            raise UnknownFenceError(f"no fence with id {fence_id!r}") from None

    def remove(self, fence_id: str) -> Fence:
        """Remove and return a fence."""
        fence = self.get(fence_id)
        del self._fences[fence_id]
        self._grid.remove(fence_id)
        return fence

    def containing(self, point: CoordinateLike, boundary: bool = True) -> list[Fence]:
        """Fences that contain the point, in id order."""
        c = as_coordinate(point)
        hits = [
            self._fences[key]
            for key in self._grid.query_point(c)
            if self._fences[key].contains(c, boundary=boundary)
        ]
        return sorted(hits, key=lambda fence: fence.id)

    def intersecting(self, box: BoundingBox) -> list[Fence]:
        """Fences whose bounding box intersects ``box``, in id order."""
        return sorted(
            (self._fences[key] for key in self._grid.query_box(box)),
            key=lambda fence: fence.id,
        )
