"""A short tour of the library.  Run with ``python examples/quickstart.py``."""

from geofence import Circle, Coordinate, Fence, FenceIndex, GeofenceEngine, distance, geohash, wkt
from geofence.units import format_distance

berlin = Coordinate(52.52, 13.405)
munich = Coordinate(48.1351, 11.582)

print("Berlin -> Munich:", format_distance(distance(berlin, munich), "km", 1))
print("Geohash of Berlin:", geohash.encode(berlin, 7))

old_town = Fence(
    "old-town",
    wkt.loads("POLYGON ((11.565 48.132, 11.585 48.132, 11.585 48.142, 11.565 48.142, 11.565 48.132))"),
    name="Munich old town",
)
station = Fence("station", Circle((48.1402, 11.5586), 250), name="Central station")

index = FenceIndex([old_town, station])
print("Fences containing Marienplatz:", [f.name for f in index.containing((48.1374, 11.5755))])
nearest, metres = index.nearest(berlin)[0]
print(f"Nearest fence to Berlin: {nearest.name} ({format_distance(metres, 'km', 0)})")

engine = GeofenceEngine([old_town, station], hysteresis_m=30, dwell_s=120)
walk = [
    (0, (48.1402, 11.5586)),  # at the station
    (120, (48.1395, 11.5600)),  # still there two minutes later
    (300, (48.1390, 11.5640)),  # walking east
    (480, (48.1374, 11.5755)),  # Marienplatz
    (900, (48.1300, 11.5900)),  # gone
]
for seconds, point in walk:
    for event in engine.update("walker", seconds, point):
        print(f"t={seconds:>3}s {event.type.value:<5} {event.fence_id} (after {event.duration_s:g}s)")
