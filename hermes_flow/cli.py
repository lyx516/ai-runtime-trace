"""Local validation and debug CLI entry points."""

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn


def _print_json(data: dict) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_init(args: argparse.Namespace) -> None:
    from hermes_flow.tools import flow_init
    result = flow_init(
        project_root=args.project_root,
        flow_path=args.flow,
        run_name=args.run_name,
        dry_run=args.dry_run,
    )
    _print_json(result)
    if not result.get("ok", False):
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_status — not yet implemented", "subcommand": "status"})


def cmd_step(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_step — not yet implemented", "subcommand": "step"})


def cmd_send(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_send — not yet implemented", "subcommand": "send"})


def cmd_decide(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_decide — not yet implemented", "subcommand": "decide"})


def cmd_pause(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_pause — not yet implemented", "subcommand": "pause"})


def cmd_resume(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_resume — not yet implemented", "subcommand": "resume"})


def cmd_abort(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_abort — not yet implemented", "subcommand": "abort"})


def cmd_audit(args: argparse.Namespace) -> None:
    _print_json({"error": "flow_audit — not yet implemented", "subcommand": "audit"})


def cmd_context(args: argparse.Namespace) -> None:
    """Print generated context packet for a role."""
    from hermes_flow.schemas import FlowRun
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.flow_loader import load_flow_from_yaml
    from hermes_flow.context import build_context_packet

    run_dir = Path(args.project_root) if hasattr(args, 'project_root') and args.project_root else Path.cwd()
    run_dir = run_dir / ".hermes-flow" / "runs" / args.run_id

    try:
        store = RuntimeStore(run_dir)
        flow_file = Path(store.connect().execute(
            "SELECT flow_id FROM runs WHERE run_id = ?", (args.run_id,)
        ).fetchone()[0])

        flow = load_flow_from_yaml(store.run_dir / flow_file)
        run = store.resume_run(args.run_id)
        # Simple lookup — real implementation would load from persisted state
        _print_json({"error": "context: requires full flow + state lookup — implement in US2"})
    except Exception as e:
        _print_json({"error": f"context: {e}"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-flow", description="Hermes Flow FSM Agent Loop")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_init = sub.add_parser("init", help="Initialize a new flow run")
    p_init.add_argument("--flow", required=True)
    p_init.add_argument("--project-root", required=True)
    p_init.add_argument("--run-name", default="")
    p_init.add_argument("--dry-run", action="store_true")

    p_status = sub.add_parser("status", help="Inspect run status")
    p_status.add_argument("--run-id", required=True)

    p_step = sub.add_parser("step", help="Execute next state action or gate evaluation")
    p_step.add_argument("--run-id", required=True)
    p_step.add_argument("--max-actions", type=int, default=1)

    p_send = sub.add_parser("send", help="Send a runtime message")
    p_send.add_argument("--run-id", required=True)
    p_send.add_argument("--state", required=True)
    p_send.add_argument("--from", dest="from_role", required=True)
    p_send.add_argument("--to", required=True, help="Comma-separated recipients")
    p_send.add_argument("--kind", default="proposal")
    p_send.add_argument("--content", required=True)
    p_send.add_argument("--visibility", default="targeted")
    p_send.add_argument("--requires-ack", action="store_true")

    p_decide = sub.add_parser("decide", help="Record a gate decision")
    p_decide.add_argument("--run-id", required=True)
    p_decide.add_argument("--state", required=True)
    p_decide.add_argument("--role", required=True)
    p_decide.add_argument("--value", required=True)
    p_decide.add_argument("--reason", default="")

    p_pause = sub.add_parser("pause", help="Pause an active run")
    p_pause.add_argument("--run-id", required=True)
    p_pause.add_argument("--reason", required=True)

    p_resume = sub.add_parser("resume", help="Resume a paused or escalated run")
    p_resume.add_argument("--run-id", required=True)
    p_resume.add_argument("--continuation-state", default="")

    p_abort = sub.add_parser("abort", help="Abort a run")
    p_abort.add_argument("--run-id", required=True)
    p_abort.add_argument("--reason", required=True)

    p_audit = sub.add_parser("audit", help="Export audit trail")
    p_audit.add_argument("--run-id", required=True)

    p_context = sub.add_parser("context", help="Print generated context packet for a role")
    p_context.add_argument("--run-id", required=True)
    p_context.add_argument("--role", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "init": cmd_init,
        "status": cmd_status,
        "step": cmd_step,
        "send": cmd_send,
        "decide": cmd_decide,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "abort": cmd_abort,
        "audit": cmd_audit,
        "context": cmd_context,
    }

    handler = handlers.get(args.subcommand)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
