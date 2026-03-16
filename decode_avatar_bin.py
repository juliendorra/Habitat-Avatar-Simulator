"""
decode_avatar_bin.py
====================
Decode Habitat Avatar.bin into individual body-part cel PNGs.

Avatar.bin contains the normal human avatar body with 6 limbs:
  0: Legs (right)   1: Legs (left)   2: Left Arm
  3: Torso          4: Head placeholder   5: Right Arm

Each limb has multiple animation states (standing, walking, sitting, etc.)
and each state references one or more cels.

Cel format (6-byte header + RLE pixel data):
  Byte 0: type(7-6) | width_bytes(3-0)  (width in bytes, *4 for pixels)
  Byte 1: height in scanlines
  Byte 2: x_offset (signed)
  Byte 3: y_offset (signed, from bottom)
  Byte 4: x_rel (signed, displacement to next cel)
  Byte 5: y_rel (signed, displacement to next cel)

Pixel encoding: 2 bits per pixel, 4 pixels per byte
  00 = transparent
  01 = outline (black)
  10 = foreground
  11 = wild/pattern
"""

import os
import struct
import json
from PIL import Image
import numpy as np

# C64 Pepto palette - true Commodore 64 colors
C64_PALETTE = {
    0: (0, 0, 0),        # Black
    1: (255, 255, 255),   # White
    2: (104, 55, 43),     # Red
    3: (112, 164, 178),   # Cyan
    4: (111, 61, 134),    # Purple
    5: (88, 141, 67),     # Green
    6: (53, 40, 121),     # Blue
    7: (184, 199, 111),   # Yellow
    8: (111, 79, 37),     # Orange
    9: (67, 57, 0),       # Brown
    10: (154, 103, 89),   # Light Red / Pink
    11: (68, 68, 68),     # Dark Gray
    12: (108, 108, 108),  # Medium Gray
    13: (154, 210, 132),  # Light Green
    14: (108, 94, 181),   # Light Blue
    15: (149, 149, 149),  # Light Gray
}

# Default avatar cel colors (what the game used)
# Pixel value mapping:
# 0 = transparent
# 1 = outline color (black, C64 index 0)
# 2 = foreground (blue, C64 index 6)
# 3 = wild/pattern (light blue, C64 index 14)
AVATAR_PALETTE = [
    (0, 0, 0, 0),           # 0: transparent
    (0, 0, 0, 255),          # 1: outline (black)
    (53, 40, 121, 255),      # 2: foreground (C64 blue)
    (108, 94, 181, 255),     # 3: wild/pattern (C64 light blue)
]


def signed_byte(b):
    """Convert unsigned byte to signed."""
    return b if b < 128 else b - 256


def decode_cel(data, offset):
    """Decode a single cel from binary data at the given offset.

    Returns dict with cel metadata and pixel bitmap, or None if invalid.
    """
    if offset + 6 > len(data):
        return None

    byte0 = data[offset]
    width_bytes = byte0 & 0x0F
    cel_type = (byte0 >> 6) & 0x03
    height = data[offset + 1]
    x_offset = signed_byte(data[offset + 2])
    y_offset = signed_byte(data[offset + 3])
    x_rel = signed_byte(data[offset + 4])
    y_rel = signed_byte(data[offset + 5])

    if width_bytes == 0 or height == 0 or width_bytes > 15 or height > 64:
        return None

    total_bytes = width_bytes * height
    pixel_width = width_bytes * 4  # 4 pixels per byte

    # Decode RLE pixel data
    pixel_bytes = []
    i = offset + 6
    while len(pixel_bytes) < total_bytes and i < len(data):
        b = data[i]
        i += 1
        if b == 0 and i < len(data):
            count = data[i]
            i += 1
            if (count & 0x80) == 0:
                # Value run
                if i >= len(data):
                    break
                val = data[i]
                i += 1
                pixel_bytes.extend([val] * count)
            else:
                # Transparent run
                run_len = count & 0x7F
                pixel_bytes.extend([0] * run_len)
        else:
            pixel_bytes.append(b)

    # Pad if needed
    while len(pixel_bytes) < total_bytes:
        pixel_bytes.append(0)

    # Decode into bitmap (column-major: fill column by column)
    bitmap = [[0] * pixel_width for _ in range(height)]
    for idx in range(min(len(pixel_bytes), total_bytes)):
        col = idx // height
        row = idx % height
        if col < width_bytes and row < height:
            byte_val = pixel_bytes[idx]
            for k in range(4):
                pix = (byte_val >> (6 - 2 * k)) & 0x03
                px = col * 4 + k
                # Flip vertically (C64 draws bottom-up)
                bitmap[height - 1 - row][px] = pix

    return {
        'width_bytes': width_bytes,
        'pixel_width': pixel_width,
        'height': height,
        'x_offset': x_offset,
        'y_offset': y_offset,
        'x_rel': x_rel,
        'y_rel': y_rel,
        'type': cel_type,
        'bitmap': bitmap,
        'data_end': i,
    }


def save_cel_png(cel, path, palette=None, scale=2):
    """Save a decoded cel as a PNG with optional horizontal stretch."""
    if palette is None:
        palette = AVATAR_PALETTE

    h = cel['height']
    w = cel['pixel_width']
    arr = np.zeros((h, w, 4), dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            arr[y, x] = palette[cel['bitmap'][y][x]]

    img = Image.fromarray(arr, mode='RGBA')
    # Apply C64 aspect ratio correction (2x horizontal stretch)
    if scale > 1:
        img = img.resize((w * scale, h), Image.NEAREST)

    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    img.save(path)
    return img


def decode_avatar_bin(bin_path, out_dir):
    """Decode Avatar.bin and extract all limb cels."""
    with open(bin_path, 'rb') as f:
        data = f.read()

    print(f"Avatar.bin: {len(data)} bytes")

    # Limb names
    limb_names = ['legs_right', 'legs_left', 'left_arm', 'torso', 'head_placeholder', 'right_arm']

    # Known limb offsets from the binary analysis
    limb_offsets = [0x002D, 0x05A4, 0x065E, 0x07A1, 0x08C3, 0x0941]

    # Next limb offset (or end of file) for boundary
    boundaries = limb_offsets[1:] + [len(data)]

    manifest = {}

    for limb_idx, (limb_off, boundary) in enumerate(zip(limb_offsets, boundaries)):
        limb_name = limb_names[limb_idx]
        print(f"\n--- Limb {limb_idx}: {limb_name} (offset 0x{limb_off:04X}) ---")

        if limb_off >= len(data):
            print(f"  Offset out of range!")
            continue

        # Read limb header
        header_byte = data[limb_off]
        num_states = (header_byte & 0x7F) + 1
        animation_type = 'cycle' if (header_byte & 0x80) else 'once'

        print(f"  States: {num_states}, Animation: {animation_type}")

        # State bytes follow the 3-byte header
        state_offset = limb_off + 3
        states = []
        for s in range(num_states):
            if state_offset + s < len(data):
                state_val = data[state_offset + s]
                states.append(state_val)

        print(f"  State values: {states}")

        # Find unique cel indices (excluding 0xFF which means "not drawn")
        cel_indices = sorted(set(s for s in states if s != 0xFF))
        print(f"  Unique cel indices: {cel_indices}")

        # Cel offset table follows state bytes
        cel_table_offset = state_offset + num_states
        cel_offsets = []

        for ci in range(max(cel_indices) + 1 if cel_indices else 0):
            if cel_table_offset + ci * 2 + 1 < len(data):
                # Little-endian word, relative to limb start
                lo = data[cel_table_offset + ci * 2]
                hi = data[cel_table_offset + ci * 2 + 1]
                cel_off = lo | (hi << 8)
                cel_offsets.append(cel_off)
            else:
                cel_offsets.append(None)

        print(f"  Cel offsets (relative): {['0x{:04X}'.format(c) if c else 'None' for c in cel_offsets]}")

        limb_data = {
            'name': limb_name,
            'num_states': num_states,
            'animation': animation_type,
            'states': states,
            'cels': {}
        }

        # Decode each cel
        for ci, rel_off in enumerate(cel_offsets):
            if rel_off is None:
                continue
            abs_off = limb_off + rel_off

            if abs_off >= len(data) or abs_off >= boundary:
                print(f"  Cel {ci}: offset 0x{abs_off:04X} out of range")
                continue

            cel = decode_cel(data, abs_off)
            if cel is None:
                print(f"  Cel {ci}: failed to decode at 0x{abs_off:04X}")
                continue

            print(f"  Cel {ci}: {cel['pixel_width']}x{cel['height']}px, "
                  f"offset=({cel['x_offset']},{cel['y_offset']}), "
                  f"rel=({cel['x_rel']},{cel['y_rel']})")

            # Save as PNG
            cel_path = os.path.join(out_dir, f"{limb_name}_cel{ci:02d}.png")
            save_cel_png(cel, cel_path)

            limb_data['cels'][ci] = {
                'file': f"{limb_name}_cel{ci:02d}.png",
                'width': cel['pixel_width'] * 2,  # After 2x stretch
                'height': cel['height'],
                'x_offset': cel['x_offset'],
                'y_offset': cel['y_offset'],
                'x_rel': cel['x_rel'],
                'y_rel': cel['y_rel'],
                'native_width': cel['pixel_width'],
            }

        manifest[limb_name] = limb_data

    # Save manifest
    manifest_path = os.path.join(out_dir, 'body_manifest.json')
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest saved to {manifest_path}")

    return manifest


if __name__ == '__main__':
    import sys
    bin_path = sys.argv[1] if len(sys.argv) > 1 else 'Avatar.bin'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'habitat_images_final/body'
    decode_avatar_bin(bin_path, out_dir)
