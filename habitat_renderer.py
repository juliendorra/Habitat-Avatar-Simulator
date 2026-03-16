"""
habitat_renderer.py
====================

This script converts Lucasfilm Habitat graphics source files (`.m`) into PNG
images.  The Habitat image format is not a simple raster: it stores
animation cels as a header followed by run–length encoded vertical strips
of 2‑bit pixel data.  Each byte describes four pixels and runs are
denoted with a zero byte followed by a count (and optionally a value).

The script parses the Macross assembly source files found under
`aric/mic/Gr/Heads` and `aric/mic/Gr/Props`.  It understands the `run`
macro used in those files (e.g. `run,7,9` or `run,0x80+10`) and a few
numeric formats (`0x` hex, `0b` binary, `0q` quaternary).  It expands
the macros into raw bytes, then decodes the cel headers and RLE data
into pixel arrays.  The resulting bitmap is converted to an RGBA PNG
using the classic Habitat palette: transparent, black, blue and pink
【387455118052294†L101-L106】.  If a file contains multiple cel data blocks
(`_data_a`, `_data_b`, etc.), each block will be rendered to its own
PNG.

Usage (from the repository root)::

    python3 habitat_renderer.py --src /path/to/aric/mic/Gr/Heads \
                               --out /path/to/output

The script will recurse through the source directory, render all
recognized cels and place the PNG files into the output directory
preserving the relative folder structure.  To process both Heads and
Props directories you can call it twice or specify their common parent.

"""

import argparse
import os
import re
from typing import Dict, List, Optional
from PIL import Image
import numpy as np

# Default RGBA palette used by Habitat cels.
#
# Entries correspond to the four possible pixel values in the decoded cel
# data.  The first entry must remain fully transparent.  The remaining
# three entries define the darkest, mid‑tone and highlight colours
# respectively.  These defaults reproduce the classic black/blue/pink
# appearance found in the original Habitat client, but can be overridden
# at runtime with the ``--palette`` command line argument.
PALETTE = [
    (0, 0, 0, 0),        # 0: transparent
    (0, 0, 0, 255),      # 1: darkest colour (outlines)
    (0, 0, 255, 255),    # 2: mid‑tone colour
    (255, 85, 255, 255), # 3: highlight colour
]


def eval_token(token: str) -> Optional[int]:
    """Evaluate a numeric token from the .m source.

    Supports hexadecimal (0x..), binary (0b..), quaternary (0q..), decimal and
    simple '+' expressions combining these.  Unknown tokens return None.

    Args:
        token: A single token from a `byte` line.

    Returns:
        An integer value in range 0–255 or None if not parsable.
    """
    token = token.strip()
    if not token:
        return None
    # handle expression with '+' first
    if '+' in token:
        total = 0
        for part in token.split('+'):
            part = part.strip()
            val = eval_token(part)
            if val is None:
                # if any part is unknown, skip expression
                return None
            total += val
        return total & 0xFF
    # hexadecimal
    if token.lower().startswith("0x"):
        try:
            return int(token, 16) & 0xFF
        except ValueError:
            return None
    # binary
    if token.lower().startswith("0b"):
        try:
            return int(token, 2) & 0xFF
        except ValueError:
            return None
    # quaternary (two-bit digits)
    if token.lower().startswith("0q"):
        try:
            return int(token[2:], 4) & 0xFF
        except ValueError:
            return None
    # decimal
    if token.isdigit():
        return int(token) & 0xFF
    # fallback: extract digits if present
    m = re.search(r"([0-9]+)", token)
    if m:
        try:
            return int(m.group(1)) & 0xFF
        except ValueError:
            return None
    return None


def expand_tokens(tokens: List[str]) -> List[int]:
    """Expand a list of tokens into raw bytes.

    Implements the Habitat `run` macro as used in the graphics sources.
    `run,n,value` emits three bytes: 0x00, n, value.  `run,0x80+m`
    emits two bytes: 0x00, 0x80+m and signifies a transparent run of
    length m.  Non-numeric tokens are ignored.

    Args:
        tokens: A list of tokens from `byte` directives.

    Returns:
        A list of integers representing the compiled bytes.
    """
    result: List[int] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == 'run':
            # next token must exist
            if i + 1 >= len(tokens):
                break
            next_tok = tokens[i + 1]
            count = eval_token(next_tok)
            if count is None:
                i += 1
                continue
            if count >= 0x80:
                # transparent run: output run marker and count
                result.append(0)
                result.append(count & 0xFF)
                i += 2
            else:
                # require a third token for the value
                if i + 2 >= len(tokens):
                    break
                val = eval_token(tokens[i + 2])
                if val is not None:
                    result.append(0)
                    result.append(count & 0xFF)
                    result.append(val & 0xFF)
                i += 3
        else:
            val = eval_token(tok)
            if val is not None:
                result.append(val & 0xFF)
            i += 1
    return result


def decode_bitmap(data: List[int]) -> Optional[List[List[int]]]:
    """Decode a raw Habitat bitmap into a 2‑D array of pixel values.

    The first six bytes of the data are the cel header.  The low nibble
    of byte 0 is the width in bytes, byte 1 is the height.  Pixel
    values are encoded in vertical strips using run–length encoding
    where each byte represents four 2‑bit pixels.  A zero byte
    denotes a run marker: if the following count has its high bit set
    (>=0x80) then a transparent run of (count & 0x7F) bytes is
    inserted; otherwise the next byte is the value to repeat for the
    given count.

    Args:
        data: A list of integers representing the cel bytes.

    Returns:
        A two‑dimensional list of ints (0–3) representing pixel values,
        or None if the header is invalid.
    """
    # validate header
    if len(data) < 6:
        return None
    width_bytes = data[0] & 0x0F
    height = data[1]
    if width_bytes == 0 or height == 0:
        return None
    total_bytes = width_bytes * height
    # expand run‑length encoded pixel bytes into a flat list of length total_bytes
    pixel_bytes: List[int] = []
    i = 6
    while len(pixel_bytes) < total_bytes and i < len(data):
        b = data[i]
        i += 1
        if b == 0 and i < len(data):
            count = data[i]
            i += 1
            if (count & 0x80) == 0:
                # the next byte is repeated count times
                if i >= len(data):
                    break
                val = data[i]
                i += 1
                pixel_bytes.extend([val] * count)
            else:
                # transparent run of count&0x7F bytes (zeroes)
                run_len = count & 0x7F
                pixel_bytes.extend([0] * run_len)
        else:
            pixel_bytes.append(b)
    # pad with zeros if truncated
    if len(pixel_bytes) < total_bytes:
        pixel_bytes += [0] * (total_bytes - len(pixel_bytes))
    # helper: decode pixel_bytes into bitmap using mapping function
    def decode_orientation(mapper):
        bmp = [[0] * (width_bytes * 4) for _ in range(height)]
        for idx, val in enumerate(pixel_bytes[:total_bytes]):
            x_byte, y = mapper(idx)
            if 0 <= x_byte < width_bytes and 0 <= y < height:
                for k in range(4):
                    pix = (val >> (6 - 2 * k)) & 0x03
                    bmp[height - 1 - y][x_byte * 4 + k] = pix
        return bmp
    # vertical mapper: fill column by column (original orientation)
    def vertical_mapper(ibmp):
        return ibmp // height, ibmp % height
    # horizontal mapper: fill row by row (alternative orientation)
    def horizontal_mapper(ibmp):
        return ibmp % width_bytes, ibmp // width_bytes
    bmp_vert = decode_orientation(vertical_mapper)
    bmp_horiz = decode_orientation(horizontal_mapper)
    # decide orientation by choosing the bitmap with more non‑transparent pixels
    count_vert = sum(1 for row in bmp_vert for p in row if p != 0)
    count_horiz = sum(1 for row in bmp_horiz for p in row if p != 0)
    return bmp_horiz if count_horiz > count_vert else bmp_vert


def save_bitmap_as_png(bitmap: List[List[int]], out_path: str, *,
                       palette: Optional[List[tuple]] = None,
                       scale: int = 1) -> None:
    """Save a bitmap (2‑D list of pixel indices) as a PNG file.

    The bitmap is converted into an RGBA image using the provided
    palette.  An optional horizontal scaling factor can be used to
    compensate for the non‑square pixel aspect ratio of the C‑64: in
    Habitat, graphics were designed with rectangular pixels (wider
    than tall) so faces may appear squeezed when displayed on modern
    systems.  Scaling the image width by 2 (``--scale 2``) restores
    a more natural aspect ratio.

    Args:
        bitmap: A 2‑D list of ints 0–3.
        out_path: Destination file path for the PNG.
        palette: Optional replacement palette for the three
            non‑transparent colours.  Should be a list of four
            (R,G,B,A) tuples; if omitted the module‑level ``PALETTE``
            is used.
        scale: Horizontal scaling factor (integer ≥1).
    """
    height = len(bitmap)
    width = len(bitmap[0]) if height > 0 else 0
    if width == 0 or height == 0:
        return
    pal = palette if palette is not None else PALETTE
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = pal[bitmap[y][x]]
    img = Image.fromarray(arr, mode='RGBA')
    # optionally stretch horizontally to correct aspect ratio
    if scale > 1:
        img = img.resize((width * scale, height), Image.NEAREST)
    # ensure directory exists
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)


def parse_m_file(path: str) -> Dict[str, List[str]]:
    """Parse a .m file and return a mapping of data labels to tokens.

    The parser looks for lines beginning with a label (e.g. `foo_data_a:`)
    followed by one or more `byte` directives.  It collects the tokens
    (values separated by commas) from consecutive `byte` lines until
    another label or non‑byte line is encountered.  Comments (after `;`)
    are removed.

    Args:
        path: Path to the .m source file.

    Returns:
        A dictionary mapping label names to lists of tokens.
    """
    blocks: Dict[str, List[str]] = {}
    current_label: Optional[str] = None
    collecting = False
    tokens: List[str] = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # remove comments
            line = line.split(';')[0].strip()
            if not line:
                continue
            # detect label (foo_data_a:)
            m = re.match(r'^(\w+):$', line)
            if m:
                # save previous block
                if collecting and current_label:
                    blocks[current_label] = tokens
                current_label = m.group(1)
                tokens = []
                collecting = False
                continue
            # accumulate byte directives
            if line.startswith('byte'):
                collecting = True
                # strip 'byte' and split by commas
                rest = line[4:].strip()
                toks = [t.strip() for t in rest.split(',') if t.strip()]
                tokens.extend(toks)
            else:
                # terminate current block on any non-byte line
                if collecting and current_label:
                    blocks[current_label] = tokens
                    tokens = []
                    collecting = False
    # catch final block
    if collecting and current_label:
        blocks[current_label] = tokens
    return blocks


def process_m_file(path: str, out_dir: str, *, palette: Optional[List[tuple]] = None,
                   scale: int = 1) -> List[str]:
    """Process a single .m file and render all data blocks to PNG.

    Args:
        path: Path to the .m file.
        out_dir: Base directory for output images.
        palette: Optional custom palette to use when rendering.
        scale: Horizontal scaling factor.

    Returns:
        A list of output file paths created.
    """
    out_files: List[str] = []
    # parse the file for data blocks
    blocks = parse_m_file(path)
    base_name = os.path.splitext(os.path.basename(path))[0]
    # For each block, expand tokens and decode
    for label, tokens in blocks.items():
        data = expand_tokens(tokens)
        bmp = decode_bitmap(data)
        if bmp:
            out_name = f"{base_name}_{label}.png"
            out_path = os.path.join(out_dir, out_name)
            save_bitmap_as_png(bmp, out_path, palette=palette, scale=scale)
            out_files.append(out_path)
    return out_files


def process_directory(src_dir: str, out_dir: str, *, palette: Optional[List[tuple]] = None,
                      scale: int = 1) -> List[str]:
    """Recursively process all .m files under a directory.

    Args:
        src_dir: Root of the source tree containing .m files.
        out_dir: Directory where PNGs will be written.
        palette: Optional custom palette to use when rendering.
        scale: Horizontal scaling factor.

    Returns:
        A list of all output file paths created.
    """
    outputs: List[str] = []
    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            if fname.lower().endswith('.m'):
                path = os.path.join(root, fname)
                outputs.extend(process_m_file(path, out_dir, palette=palette, scale=scale))
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Habitat .m graphics to PNG")
    parser.add_argument('--src', type=str, required=True, help='Source directory containing .m files')
    parser.add_argument('--out', type=str, required=True, help='Output directory for PNG files')
    parser.add_argument('--palette', type=str, default=None,
                        help=(
                            'Comma‑separated list of three hex colours for the darkest, mid‑tone and highlight ' 
                            'colours (e.g. 31278d,6d5fb8,a16abb). Transparent colour is always preserved.'))
    parser.add_argument('--scale', type=int, default=1,
                        help='Horizontal scaling factor to compensate for C‑64 pixel aspect ratio (e.g. 2)')
    args = parser.parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    palette = None
    if args.palette:
        cols = [c.strip() for c in args.palette.split(',') if c.strip()]
        if len(cols) == 3:
            pal = [PALETTE[0]]
            try:
                for col in cols:
                    col = col.lstrip('#')
                    if len(col) != 6 or any(ch not in '0123456789abcdefABCDEF' for ch in col):
                        raise ValueError
                    r = int(col[0:2], 16)
                    g = int(col[2:4], 16)
                    b = int(col[4:6], 16)
                    pal.append((r, g, b, 255))
                if len(pal) == 4:
                    palette = pal
            except Exception:
                palette = None
    scale = args.scale if args.scale and args.scale > 0 else 1
    outputs = process_directory(os.path.abspath(args.src), out_dir, palette=palette, scale=scale)
    print(f"Converted {len(outputs)} images to {out_dir}")


if __name__ == '__main__':
    main()