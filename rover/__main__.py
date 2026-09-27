"""FNK0052 command-line entry point."""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from rover.config import RobotConfig
from rover.controller import FreenoveFNK0052Controller, MockHexapodController
from rover.demo import run_mock_demo
from rover.diagnostics import run_diagnostics


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("diagnostics", help="Run non-moving configuration and device checks")
    commands.add_parser("status", help="Show configured controller state without physical movement")
    commands.add_parser("demo", help="Run the finite offline FNK0052 integration simulation")
    args = parser.parse_args(argv)
    config = RobotConfig.from_env()

    if args.command == "demo":
        if config.mode != "mock":
            parser.error("demo is intentionally mock-only; set ROBOT_MODE=mock")
        result = run_mock_demo()
    elif args.command == "diagnostics":
        result = run_diagnostics(config)
    else:
        controller = (
            MockHexapodController(config.robot_id)
            if config.mode == "mock"
            else FreenoveFNK0052Controller(
                config.robot_id, config.freenove_server_path,
                allow_physical_actuation=config.allow_physical_actuation,
            )
        )
        result = controller.health_check().model_dump(mode="json")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
