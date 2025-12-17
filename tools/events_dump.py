#!/usr/bin/env python3
"""
events_dump.py – Inspect Procedura CLI events from BitStream
============================================================
Usage:
  python tools/events_dump.py [--last N] [--cmd CMD] [--out FILE] [--csv]

Examples:
  python tools/events_dump.py --last 10
  python tools/events_dump.py --cmd worldstate_snapshot --csv
"""
import argparse
import json
import sys
import csv
from datetime import datetime
from pathlib import Path

# Add project root and stack-main to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "stack-main"))

from modules.bitstream import BitStream
from procedura_sdk.metrics import EVENTS_WORLD_ID, DEFAULT_WORLD_ROOT

def main():
    parser = argparse.ArgumentParser(description="Dump Procedura CLI events")
    parser.add_argument("--last", type=int, default=20, help="Number of recent events to show")
    parser.add_argument("--cmd", type=str, help="Filter by command name")
    parser.add_argument("--out", type=str, help="Output file (JSON or CSV)")
    parser.add_argument("--csv", action="store_true", help="Output as CSV to stdout (or file)")
    parser.add_argument("--root", type=str, default=DEFAULT_WORLD_ROOT, help="World root directory")
    args = parser.parse_args()

    print(f"Reading events from: {args.root}/{EVENTS_WORLD_ID}...", file=sys.stderr)
    
    bs = BitStream(world_id=EVENTS_WORLD_ID, world_root=args.root)
    
    # BitStream doesn't have a simple 'len()' or 'tail()', so we scan backwards
    # using _discover_max_index (internal API, but efficient enough for tools)
    max_idx = bs._discover_max_index()
    
    events = []
    count = 0
    idx = max_idx
    
    while idx >= 0 and count < args.last:
        rec = bs.read(idx)
        if rec and isinstance(rec, dict):
            # Filter by cmd if requested
            if args.cmd and rec.get("cmd") != args.cmd:
                idx -= 1
                continue
                
            events.append(rec)
            count += 1
        idx -= 1

    # Sort chronological (oldest first) for display
    events.reverse()

    if args.csv or (args.out and args.out.endswith(".csv")):
        output_csv(events, args.out)
    else:
        output_json(events, args.out)

def output_json(events, filepath):
    if filepath:
        with open(filepath, "w") as f:
            json.dump(events, f, indent=2, default=str)
        print(f"Wrote {len(events)} events to {filepath}", file=sys.stderr)
    else:
        print(json.dumps(events, indent=2, default=str))

def output_csv(events, filepath):
    if not events:
        print("No events found.", file=sys.stderr)
        return

    # Flatten keys for CSV
    headers = [
        "ts", "cmd", "status", "ack_latency_ms", "final_latency_ms", 
        "msg_id", "job_id", "payload_size", "error"
    ]
    
    rows = []
    for e in events:
        row = {k: e.get(k) for k in headers}
        # Simplify args for CSV
        row["args"] = " ".join(e.get("args", []))
        rows.append(row)
        
    headers.append("args")

    out_stream = sys.stdout
    if filepath:
        out_stream = open(filepath, "w", newline="")

    try:
        writer = csv.DictWriter(out_stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if filepath:
            out_stream.close()
            print(f"Wrote {len(events)} events to {filepath}", file=sys.stderr)

if __name__ == "__main__":
    main()
