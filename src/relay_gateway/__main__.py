"""Local CLI. Live requests require a command-line flag and environment opt-in."""

import argparse
import json
from pathlib import Path

from .gateway import compare_scenario, run_scenario
from .models import Scenario, default_scenario, normalize_reference_context
from .providers import GeminiProvider


def load_references(path: Path) -> list[dict]:
    """Read bounded untrusted passages, including a saved Snowflake proof.

    A saved proof's claims are not independently authenticated by this loader.
    It only validates the reference contract before any live provider starts.
    """
    try:
        with path.open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise ValueError
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict):
            if (data.get("provider") != "snowflake" or data.get("status") != "completed"
                    or data.get("proof_verified") is not True):
                raise ValueError
            data = data["evidence"]["reference_context"]
        if not isinstance(data, list):
            raise ValueError
        return normalize_reference_context(data)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise ValueError("References must be a UTF-8 JSON list or completed Snowflake proof, at most 64 KiB, with valid bounded passages.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Relay offline fleet gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the mock mission; optional guarded Gemini call")
    demo.add_argument("--scenario", type=Path)
    demo.add_argument("--strategy", choices=["economy", "baseline"], default="economy")
    demo.add_argument("--store", default=None, help="SQLite path, or explicit 'mongodb'")
    demo.add_argument("--replay", action="store_true", help="Strictly reuse an existing recording")
    demo.add_argument("--live", action="store_true", help="Explicitly enable guarded Gemini requests")
    demo.add_argument("--references-file", type=Path,
                      help="Bounded JSON passages or saved Snowflake data proof; untrusted evidence only")
    compare = commands.add_parser("compare", help="Compare two policies offline using mock findings")
    compare.add_argument("--scenario", type=Path)
    commands.add_parser("integrations", help="Replay the integrated mission using offline adapters only")
    serve = commands.add_parser("serve", help="Serve a mock-only dashboard/API on loopback")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "integrations":
        from .integrations.workflow import run_integration_demo
        from .api import PROJECT_ROOT
        fixture = json.loads((PROJECT_ROOT / "scenarios" / "leak.json").read_text(encoding="utf-8"))
        print(json.dumps(run_integration_demo(fixture), indent=2))
        return
    if args.command == "serve":
        import uvicorn
        uvicorn.run("relay_gateway.api:app", host="127.0.0.1", port=args.port)
        return
    scenario = (Scenario.model_validate_json(args.scenario.read_text(encoding="utf-8"))
                if args.scenario else default_scenario())
    if args.command == "compare":
        result = compare_scenario(scenario)
    else:
        if args.live and args.replay:
            parser.error("Live mode and strict replay are separate workflows")
        try:
            references = load_references(args.references_file) if args.references_file else None
        except ValueError as error:
            parser.error(str(error))
        provider = GeminiProvider.from_environment() if args.live else None
        try:
            result = run_scenario(scenario, args.strategy, provider=provider,
                                  store_path=args.store, replay=args.replay,
                                  reference_context=references)
        finally:
            if provider is not None:
                provider.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
