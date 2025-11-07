# procedura_sdk/cli.py
from __future__ import annotations
import argparse
import json
import asyncio
from .remote_agent import RemoteAgent

def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def cmd_login(args):
    ra = RemoteAgent(args.url, token=args.token)
    out = ra.login_password(args.credential, replace=(not args.attach), device=args.device, ttl=args.ttl)
    _print(out)

def cmd_run(args):
    ra = RemoteAgent(args.url, token=args.token)
    out = ra.run(args.module, args.module_args or [])
    _print(out)

def cmd_stream(args):
    async def go():
        ra = RemoteAgent(args.url, token=args.token)
        async for ev in ra.run_async_stream(args.module, args.module_args or []):
            _print(ev)
    asyncio.run(go())

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

