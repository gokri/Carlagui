"""Pedestrian crossing scenario for CARLA 0.9.16."""

import random
import threading
import logging

log = logging.getLogger(__name__)

SCENARIO_LIST = [
    "Pedestrian Crossing",
    "Sudden Brake",
    "Junction Conflict",
    "Parked Car Obstruction",
]


class ScenarioRunner:
    def __init__(self, carla_client, on_log=None):
        self._client = carla_client
        self._log = on_log or (lambda m: None)
        self._actors = []

    def _cleanup(self):
        for actor in self._actors:
            try:
                actor.destroy()
            except Exception:
                pass
        self._actors.clear()

    def run(self, scenario_name: str):
        threading.Thread(target=self._run, args=(scenario_name,), daemon=True).start()

    def _run(self, scenario_name: str):
        self._cleanup()
        try:
            dispatch = {
                "Pedestrian Crossing": self._pedestrian_crossing,
                "Sudden Brake": self._sudden_brake,
                "Junction Conflict": self._junction_conflict,
                "Parked Car Obstruction": self._parked_car,
            }
            fn = dispatch.get(scenario_name)
            if fn is None:
                self._log(f"[ERR] Unknown scenario: {scenario_name}")
                return
            fn()
        except Exception as exc:
            self._log(f"[ERR] Scenario error: {exc}")

    # ------------------------------------------------------------------ scenarios
    def _pedestrian_crossing(self):
        import carla  # noqa: PLC0415
        world = self._client.world
        if not world:
            self._log("[ERR] Not connected.")
            return
        self._log("[INFO] Running: Pedestrian Crossing")
        bp_lib = world.get_blueprint_library()
        walker_bps = bp_lib.filter("walker.pedestrian.*")
        controller_bp = bp_lib.find("controller.ai.walker")
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            self._log("[ERR] No spawn points.")
            return
        # Spawn 3 pedestrians near a random spawn point
        base = random.choice(spawn_points)
        for i in range(3):
            bp = random.choice(list(walker_bps))
            if bp.has_attribute("is_invincible"):
                bp.set_attribute("is_invincible", "true")
            loc = carla.Location(
                base.location.x + i * 2.0,
                base.location.y + 4.0,
                base.location.z + 1.0,
            )
            transform = carla.Transform(loc)
            walker = world.try_spawn_actor(bp, transform)
            if walker:
                self._actors.append(walker)
                controller = world.spawn_actor(controller_bp, carla.Transform(), attach_to=walker)
                self._actors.append(controller)
                world.tick()
                controller.start()
                # Walk toward the road
                target = carla.Location(loc.x, loc.y - 8.0, loc.z)
                controller.go_to_location(target)
                controller.set_max_speed(1.4)
        self._log(f"[OK] Spawned {len([a for a in self._actors if 'walker' in a.type_id])} pedestrians crossing.")

    def _sudden_brake(self):
        import carla  # noqa: PLC0415
        world = self._client.world
        if not world:
            return
        self._log("[INFO] Running: Sudden Brake — spawning lead vehicle with autopilot")
        bp = random.choice(list(world.get_blueprint_library().filter("vehicle.tesla.*")))
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            return
        t = random.choice(spawn_points)
        actor = world.try_spawn_actor(bp, t)
        if actor:
            actor.set_autopilot(True)
            self._actors.append(actor)
            self._log(f"[OK] Lead vehicle spawned: {actor.type_id}")

    def _junction_conflict(self):
        import carla  # noqa: PLC0415
        world = self._client.world
        if not world:
            return
        self._log("[INFO] Running: Junction Conflict — spawning 2 crossing vehicles")
        bps = list(world.get_blueprint_library().filter("vehicle.*"))
        spawn_points = world.get_map().get_spawn_points()
        for sp in random.sample(spawn_points, min(2, len(spawn_points))):
            bp = random.choice(bps)
            actor = world.try_spawn_actor(bp, sp)
            if actor:
                actor.set_autopilot(True)
                self._actors.append(actor)
        self._log(f"[OK] Spawned {len(self._actors)} junction vehicles.")

    def _parked_car(self):
        import carla  # noqa: PLC0415
        world = self._client.world
        if not world:
            return
        self._log("[INFO] Running: Parked Car Obstruction")
        bps = list(world.get_blueprint_library().filter("vehicle.*"))
        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            return
        sp = random.choice(spawn_points)
        bp = random.choice(bps)
        actor = world.try_spawn_actor(bp, sp)
        if actor:
            # Parked — no autopilot, no control
            self._actors.append(actor)
            self._log(f"[OK] Parked vehicle spawned: {actor.type_id} at {sp.location}")

    def cleanup(self):
        self._cleanup()
        self._log("[INFO] Scenario actors removed.")
