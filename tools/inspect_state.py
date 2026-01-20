import sys
import json
import base64
import zstandard as zstd

import os
import glob

def decode_payload(b85_str):
    try:
        compressed = base64.b85decode(b85_str)
        decompressed = zstd.ZstdDecompressor().decompress(compressed)
        return json.loads(decompressed)
    except Exception as e:
        return f"Error decoding: {e}"

def inspect_chain_file(filepath):
    print(f"--- Inspecting {filepath} ---")
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        for dbit in data.get('dbits', []):
            lbit0_data_str = dbit.get('lbit0_data')
            try:
                lbit0_data = json.loads(lbit0_data_str)
                payload_b85 = lbit0_data.get('payload')
                if lbit0_data.get('c') and payload_b85:
                    decoded = decode_payload(payload_b85)
                    print(json.dumps(decoded, indent=2))
                else:
                    print(lbit0_data)
            except json.JSONDecodeError:
                print(f"Raw data: {lbit0_data_str}")
    except Exception as e:
        print(f"Error reading file: {e}")
    print("\n")

def find_and_inspect(path):
    if os.path.isfile(path):
        inspect_chain_file(path)
    elif os.path.isdir(path):
        # Recursively find all .json files in 'chain' directories
        pattern = os.path.join(path, "**", "chain", "*.json")
        files = sorted(glob.glob(pattern, recursive=True))
        if not files:
            # Fallback: just look for any json files if structure doesn't match
            files = sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))
            
        if not files:
            print(f"No JSON files found in {path}")
            return

        print(f"Found {len(files)} chain files in {path}...")
        for f in files:
            inspect_chain_file(f)
    else:
        print(f"Path not found: {path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_state.py <file_or_directory> ...")
    else:
        for path in sys.argv[1:]:
            find_and_inspect(path)
