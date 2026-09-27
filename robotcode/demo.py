"""Finite offline fleet rehearsal. Every arrival and handoff is synthetic.

This coordinator does not dispatch the existing Relay API or the team backend.
It deliberately has no live option and never imports vendor motor libraries.
"""

import argparse
from copy import deepcopy
import json

from robotcode.arm.controller import ArmController
from robotcode.hexapod.controller import HexapodController
from robotcode.quarky_intellio_rover import RoverController


class DemoMission:
    """Synchronous demo only: one rover, one carrier, one arm station."""

    def __init__(self):
        self.rover = RoverController()
        self.hexapod = HexapodController()
        self.arm = ArmController(inventory=["inspection-kit"])
        self.events = []
        self.needs_review = False
        self._sequence = 0

    def send(self, robot, action, **params):
        if self.needs_review:
            raise ValueError("Mission requires review after interrupted operation")
        self._sequence += 1
        try:
            receipt = robot.command(f"demo-{self._sequence}", action, **params)
            if receipt["state"] == "stopped" or receipt["fault"] is not None:
                raise RuntimeError("Robot stopped; mission requires review")
        except Exception:
            self.needs_review = True
            # Try every stop even when one device reports failure.
            for device in (self.rover, self.hexapod, self.arm):
                try:
                    device.command(f"abort-{self._sequence}", "stop", reason="mission_abort")
                except Exception:
                    pass
            raise
        self.events.append({"sequence": self._sequence, "robot_id": robot.robot_id,
                            "action": action, "params": deepcopy(params), "receipt": receipt,
                            "confirmation_source": "synthetic_fixture", "simulated": True})
        return receipt

    def travel(self, target):
        self.send(self.hexapod, "dispatch", target=target)
        self.send(self.hexapod, "arrive", target=target)

    def transfer(self, direction, payload_id="inspection-kit", station_id="station-a"):
        """Paired handshake. No carrier departure before both confirmations."""
        self.send(self.hexapod, "dock", station_id=station_id)
        transfer_id = f"transfer-{self._sequence}"
        self.send(self.hexapod, "prepare_transfer", station_id=station_id,
                  transfer_id=transfer_id, payload_id=payload_id, direction=direction)
        self.send(self.arm, "prepare_transfer", station_id=station_id,
                  peer_id=self.hexapod.robot_id, transfer_id=transfer_id,
                  payload_id=payload_id, direction=direction,
                  peer_docked=True, zone_clear=True)
        self.send(self.arm, "confirm_transfer", transfer_id=transfer_id,
                  payload_secured=True, arm_clear=True)
        self.send(self.hexapod, "confirm_transfer", transfer_id=transfer_id,
                  payload_secured=True, arm_clear=True)
        self.send(self.hexapod, "undock", arm_clear=True)

    def result(self, workflow):
        return {"workflow": workflow, "simulated": True, "hardware_connected": False,
                "model_calls": 0, "api_cloud_cost_usd": 0,
                "needs_review": self.needs_review, "events": deepcopy(self.events),
                "robots": [robot.snapshot() for robot in (self.rover, self.hexapod, self.arm)]}


def run_demo(workflow="basic"):
    if workflow not in {"basic", "directed", "inspection-only", "report-only"}:
        raise ValueError("Unknown demo workflow")
    mission = DemoMission()
    mission.send(mission.rover, "patrol", waypoints=["corridor-a", "suspect-area"])
    mission.send(mission.rover, "scan", obstacle_cm=100, hazard_detected=False,
                 evidence_ref="fixture-clear-1")
    mission.send(mission.rover, "arrive", target="corridor-a")
    if workflow == "directed":
        mission.send(mission.rover, "investigate", target="suspect-area")
        mission.send(mission.rover, "scan", obstacle_cm=100, hazard_detected=False,
                     evidence_ref="fixture-directed-1")
        mission.send(mission.rover, "arrive", target="suspect-area")
        mission.send(mission.rover, "complete_inspection", evidence_ref="fixture-directed-2")
    else:
        mission.send(mission.rover, "scan", obstacle_cm=80, hazard_detected=True,
                     evidence_ref="fixture-suspected-hazard-1")
    if workflow != "report-only":
        if workflow in {"basic", "directed"}:
            mission.travel("station-a")
            mission.transfer("load")
        mission.travel("suspect-area")
        mission.send(mission.hexapod, "inspect", evidence_ref="fixture-close-inspection-1")
        if workflow in {"basic", "directed"}:
            mission.travel("station-a")
            mission.transfer("unload")
    return mission.result(workflow)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=["basic", "directed", "inspection-only", "report-only"],
                        default="basic")
    args = parser.parse_args(argv)
    print(json.dumps(run_demo(args.workflow), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
