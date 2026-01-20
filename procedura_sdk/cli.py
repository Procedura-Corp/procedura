# procedura_sdk/cli.py
from __future__ import annotations
import argparse
import json
import asyncio
from .remote_agent import RemoteAgent
from .metrics import get_metrics

def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def _update_cli_stats(cmd_name: str, success: bool):
    """Example usage of DeltaRAM to track CLI usage stats."""
    try:
        metrics = get_metrics()
        # 1. Load current state (lazy loaded from DeltaRAM)
        # Note: DeltaRAM behaves like a dict
        stats = metrics.state.get("cli_stats", {})
        
        # 2. Update counters
        total_runs = stats.get("total_runs", 0) + 1
        cmd_runs = stats.get(f"runs_{cmd_name}", 0) + 1
        
        stats["total_runs"] = total_runs
        stats[f"runs_{cmd_name}"] = cmd_runs
        
        if not success:
            stats["error_count"] = stats.get("error_count", 0) + 1

        # 3. Save state (DeltaRAM will calculate diff and persist)
        metrics.set_state("cli_stats", stats)
    except Exception:
        pass # Don't crash CLI on stats error

def cmd_login(args):
    success = False
    try:
        ra = RemoteAgent(args.url, token=args.token)
        out = ra.login_password(
            args.credential,
            replace=(not args.attach),
            device=args.device,
            ttl=args.ttl,
        )
        _print(out)
        # Check if response is an error and save it
        if isinstance(out, dict) and out.get("status") == "error":
            get_metrics().save_error(out)
        else:
            success = True
    except Exception as e:
        error_dict = {"status": "error", "message": str(e), "cmd": "login"}
        _print(error_dict)
        get_metrics().save_error(error_dict)
        raise SystemExit(1)
    finally:
        _update_cli_stats("login", success)

def cmd_run(args):
    success = False
    try:
        ra = RemoteAgent(args.url, token=args.token)
        out = ra.run(
            args.module,
            args.module_args or [],
            ack_timeout=args.ack_timeout,
            final_timeout=args.final_timeout,
        )
        _print(out)
        # Check if response is an error and save it
        if isinstance(out, dict) and out.get("status") == "error":
            get_metrics().save_error(out)
        else:
            success = True
    except Exception as e:
        error_dict = {"status": "error", "message": str(e), "cmd": "run", "module": args.module}
def cmd_stream(args):
    success = False
    error_detected = False
    async def go():
        nonlocal error_detected
        ra = RemoteAgent(args.url, token=args.token)
        async for ev in ra.run_async_stream(
            args.module,
            args.module_args or [],
            # Optional: could add ack_timeout for async in future
        ):
            _print(ev)
            # Check if any event is an error
            if isinstance(ev, dict) and ev.get("status") == "error":
                get_metrics().save_error(ev)
                error_detected = True
    try:
        asyncio.run(go())
        if not error_detected:
            success = True
    except Exception as e:
        error_dict = {"status": "error", "message": str(e), "cmd": "stream", "module": args.module}
        _print(error_dict)
        get_metrics().save_error(error_dict)
        raise SystemExit(1)
    finally:
        _update_cli_stats("stream", success)

def main(argv=None):
    p = argparse.ArgumentParser(prog="procedura", description="Procedura SDK CLI (WSS)")
    p.add_argument("--url", default="ws://127.0.0.1:8765", help="ws:// or wss:// server")
    p.add_argument("--token", default=None, help="session token (else ~/.procedura/token)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # login
    lp = sub.add_parser("login", help="Password login; saves token")
    lp.add_argument("credential", help='"email:password" or b64 string (optionally prefixed with b64:)')
    lp.add_argument("--attach", action="store_true", help="Prefer attach over replace")
    lp.add_argument("--device", default="cli", help="Reuse key device label")
    lp.add_argument("--ttl", type=int, default=3600, help="Session TTL seconds")
    lp.set_defaults(func=cmd_login)

    # run (sync)
    rp = sub.add_parser("run", help="Run a module synchronously")
    rp.add_argument("module", help="Module name (e.g., worldstate_snapshot)")
    rp.add_argument("module_args", nargs="*", help="Args after '--' go to module")
    rp.add_argument("--ack-timeout", type=float, default=10.0, help="Seconds to wait for ack (default 10)")
    rp.add_argument("--final-timeout", type=float, default=600.0, help="Seconds to wait for final result (default 600)")
    rp.set_defaults(func=cmd_run)

    # stream (async)
    sp = sub.add_parser("stream", help="Run a module with streaming updates")
    sp.add_argument("module", help="Module name")
    sp.add_argument("module_args", nargs="*", help="Args after '--' go to module")
    sp.set_defaults(func=cmd_stream)

    args, unknown = p.parse_known_args(argv)
    # support `procedura run worldstate_snapshot -- --terse`
    if args.cmd in {"run", "stream"} and unknown and unknown[0] == "--":
        unknown = unknown[1:]
        args.module_args = (args.module_args or []) + unknown
    args.func(args)

if __name__ == "__main__":
    main()

