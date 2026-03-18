#!/usr/bin/env python3
"""Extract per-head configuration data from C64 Habitat head .m source files.

Parses the header section of each head .m file to extract:
- disk_face flags (back overlay, face overlay, no-bend)
- start_end table (8 bytes mapping facing values to cel states)
- num_states
- per-state cel bitmasks
- per-cel headers (x_offset, y_offset, width, height)

Outputs a JSON file with all head data for use by the simulator.
"""

import json
import re
import subprocess
import sys
import os

def fetch_head_file(path):
    """Fetch a head .m file from the GitHub repo."""
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/Museum-of-Art-and-Digital-Entertainment/habitat/contents/{path}',
             '--jq', '.content'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        import base64
        return base64.b64decode(result.stdout.strip()).decode('utf-8', errors='replace')
    except Exception:
        return None

def parse_head_m(content, name):
    """Parse a head .m file and extract header data."""
    lines = content.split('\n')

    result = {
        'name': name,
        'num_states': 0,
        'disk_face': 0,
        'disk_face_flags': {},
        'start_end': [],
        'cel_bitmasks': [],
        'walk_offsets': [],
    }

    # Find the data section
    in_data = False
    data_bytes = []
    start_end_label = None
    in_start_end = False
    cel_headers = {}
    current_cel = None

    for line in lines:
        line = line.strip()

        # Skip comments and empty lines
        if not line or line.startswith(';'):
            continue

        # Remove inline comments
        if ';' in line:
            line = line[:line.index(';')].strip()

        # Detect data start
        if f'{name}_data::' in line or f'{name}_data:' in line:
            in_data = True
            continue

        # Detect start_end label
        if f'{name}_start_end' in line and ':' in line:
            in_start_end = True
            # Check if byte data on same line after label
            after_label = line.split(':', 1)[-1].strip() if ':' in line else ''
            if after_label.startswith('byte'):
                vals = parse_byte_line(after_label)
                result['start_end'] = vals
                in_start_end = False
            continue

        # Detect cel data labels
        cel_match = re.match(rf'{re.escape(name)}_data_([a-g])\s*:', line)
        if cel_match:
            current_cel = cel_match.group(1)
            continue

        if not in_data and not in_start_end and not current_cel:
            continue

        # Parse byte directives
        if line.startswith('byte'):
            vals = parse_byte_line(line)

            if in_start_end:
                result['start_end'].extend(vals)
                if len(result['start_end']) >= 8:
                    in_start_end = False
                continue

            if current_cel:
                # First byte line after cel label is the 6-byte header
                if current_cel not in cel_headers and len(vals) >= 4:
                    # Parse cel header: width_bytes, height, x_offset, y_offset
                    cel_headers[current_cel] = {
                        'width_bytes': vals[0] & 0x0F,
                        'height': vals[1] & 0x7F,
                        'x_offset': vals[2] if vals[2] < 128 else vals[2] - 256,
                        'y_offset': vals[3] if vals[3] < 128 else vals[3] - 256,
                    }
                continue

            if in_data:
                data_bytes.extend(vals)

        # Parse word directives (cel offsets)
        if line.startswith('word'):
            continue

    # Interpret the collected data bytes
    if len(data_bytes) >= 5:
        # Byte 0: swing + N (N = num_states - 1)
        raw_b0 = data_bytes[0]
        result['num_states'] = (raw_b0 & 0x3F) + 1

        # Byte 1: disk_face flags
        df = data_bytes[1]
        result['disk_face'] = df
        result['disk_face_flags'] = {
            'has_back_cel': bool(df & 0x80),
            'has_face_cel': bool(df & 0x40),
            'no_bend': bool(df & 0x20),
        }

        # Bytes 4-6: walk offsets (after byte 2=start_end_offset, byte 3=container)
        if len(data_bytes) >= 7:
            result['walk_offsets'] = data_bytes[4:7]

        # Bytes 7+: per-state cel bitmasks
        ns = result['num_states']
        if len(data_bytes) >= 7 + ns:
            for i in range(ns):
                bm = data_bytes[7 + i]
                result['cel_bitmasks'].append(format(bm, '08b'))

    result['cel_headers'] = cel_headers

    return result

def parse_byte_line(line):
    """Parse a 'byte' directive and return list of integer values."""
    # Remove 'byte' keyword
    line = re.sub(r'^byte\s+', '', line).strip()

    vals = []
    for part in line.split(','):
        part = part.strip()
        if not part:
            continue
        val = eval_token(part)
        if val is not None:
            vals.append(val & 0xFF)
    return vals

# Known constants from the C64 source
CONSTANTS = {
    'swing': 0,
    'cycle': 0x80,
    'no_cont': 0,
    'right': 0,
    'left': 0,
    'run': None,  # skip RLE markers
}

def eval_token(token):
    """Evaluate a single token to an integer value."""
    token = token.strip()

    # Handle binary
    if token.startswith('0b'):
        try:
            return int(token, 2)
        except ValueError:
            return None

    # Handle hex
    if token.startswith('0x') or token.startswith('$'):
        try:
            return int(token.replace('$', '0x'), 16)
        except ValueError:
            return None

    # Handle expressions with + and -
    if '+' in token and not token.startswith('0x'):
        parts = token.split('+')
        total = 0
        for p in parts:
            v = eval_token(p.strip())
            if v is None:
                return None
            total += v
        return total

    # Handle known constants
    for name, val in CONSTANTS.items():
        if token == name:
            return val

    # Handle plain integers
    try:
        return int(token)
    except ValueError:
        return None


def main():
    # Read list of head files
    head_files_path = '/tmp/habitat_head_files.txt'
    if not os.path.exists(head_files_path):
        print("Run: gh api ... | grep ... > /tmp/habitat_head_files.txt first")
        sys.exit(1)

    with open(head_files_path) as f:
        paths = [l.strip() for l in f if l.strip()]

    all_heads = {}
    errors = []

    for path in paths:
        name = os.path.basename(path).replace('.m', '')
        print(f"Processing {name}...", end=' ', flush=True)

        content = fetch_head_file(path)
        if not content:
            print("FETCH ERROR")
            errors.append(name)
            continue

        try:
            data = parse_head_m(content, name)
            all_heads[name] = data
            print(f"OK ({data['num_states']} states, disk_face=0x{data['disk_face']:02X})")
        except Exception as e:
            print(f"PARSE ERROR: {e}")
            errors.append(name)

    # Save output
    out_path = os.path.join(os.path.dirname(__file__), 'habitat_images_final', 'heads', 'head_config.json')
    with open(out_path, 'w') as f:
        json.dump(all_heads, f, indent=2)

    print(f"\nSaved {len(all_heads)} heads to {out_path}")
    if errors:
        print(f"Errors: {errors}")


if __name__ == '__main__':
    main()
