"""Route planning wrapper for CARLA 0.9.16."""

import math
import logging

log = logging.getLogger(__name__)


def _dist(a, b):
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


class RoutePlanner:
    """Wraps CARLA GlobalRoutePlanner when available, falls back to raw waypoints."""

    def __init__(self, carla_client):
        self._client = carla_client

    def plan(self, start_transform, end_transform, resolution: float = 2.0):
        """Return list of (x, y, z) tuples representing the route."""
        world = self._client.world
        if not world:
            return []
        try:
            # Try agents GlobalRoutePlanner (bundled with CARLA PythonAPI)
            from agents.navigation.global_route_planner import GlobalRoutePlanner  # noqa
            grp = GlobalRoutePlanner(world.get_map(), resolution)
            route = grp.trace_route(start_transform.location, end_transform.location)
            return [(wp.transform.location.x, wp.transform.location.y, wp.transform.location.z)
                    for wp, _ in route]
        except ImportError:
            pass
        # Fallback: nearest waypoint chain via topology
        try:
            cmap = world.get_map()
            start_wp = cmap.get_waypoint(start_transform.location)
            end_wp = cmap.get_waypoint(end_transform.location)
            visited, path = set(), [start_wp]
            current = start_wp
            for _ in range(500):
                nxt = current.next(resolution)
                if not nxt:
                    break
                current = min(nxt, key=lambda w: _dist(w.transform.location, end_wp.transform.location))
                key = (round(current.transform.location.x, 1), round(current.transform.location.y, 1))
                if key in visited:
                    break
                visited.add(key)
                path.append(current)
                if _dist(current.transform.location, end_wp.transform.location) < resolution * 2:
                    break
            return [(w.transform.location.x, w.transform.location.y, w.transform.location.z)
                    for w in path]
        except Exception as exc:
            log.warning("route_planner fallback failed: %s", exc)
            return []

    def get_map_topology(self):
        """Return list of ((x1,y1),(x2,y2)) road segments for 2D rendering."""
        world = self._client.world
        if not world:
            return []
        try:
            topology = world.get_map().get_topology()
            segments = []
            for w1, w2 in topology:
                l1 = w1.transform.location
                l2 = w2.transform.location
                segments.append(((l1.x, l1.y), (l2.x, l2.y)))
            return segments
        except Exception as exc:
            log.warning("get_map_topology: %s", exc)
            return []

    def get_spawn_points(self):
        """Return list of carla.Transform spawn points."""
        world = self._client.world
        if not world:
            return []
        try:
            return world.get_map().get_spawn_points()
        except Exception:
            return []
