# Habitat Avatar Simulator - Technical Notes

## Overview
A web-based simulator for exploring and combining avatar possibilities from Lucasfilm's Habitat (1986), the first graphical MMO virtual world. The simulator reconstructs the avatar assembly system by porting the rendering logic from the original C64 6502 assembly source code.

## C64 Source Files (Ground Truth)
All rendering logic is derived from the original source at `Museum-of-Art-and-Digital-Entertainment/habitat`:

| File | Purpose |
|------|---------|
| `sources/c64/Main/animate.m` | `display_avatar`, `draw_a_limb`, limb position tables, draw order |
| `sources/c64/Main/paint.m` | `paint_1` (cel positioning), `paint_2` (pixel rendering), `pick_pattern`, `cel_patterns` table |
| `sources/c64/Main/mix.m` | `get_cel_xy`, `find_cel_xy` (position chaining), `draw_prop`, `draw_contained_object` |
| `sources/c64/Main/chore.m` | Choreography system, facing states, action sequences |
| `sources/c64/Images/Avatar.bin` | Binary body cel data (3442 bytes), includes start_end animation tables |
| `sources/c64/Images/Heads/*.m` | Head cel data as macro assembler source (171 files) |
| `sources/c64/Images/Props/bottle.m` | Spray-on body color object (pattern preview) |

## Avatar Body Structure

### 6 Limbs (from Avatar.bin)
The avatar body is composed of exactly 6 limbs, always processed in index order 0-5:

| Index | Name | Cels | Role |
|-------|------|------|------|
| 0 | legs_right | 15 | Primary legs — walk cycle, standing, sitting |
| 1 | legs_left | 4 | Secondary leg overlay — visible during walk stride |
| 2 | left_arm | 7 | Left arm — mostly visible in front/back views |
| 3 | torso | 6 | Body — side, front, back, and bend variants |
| 4 | head_placeholder | 4 | Neck/collar anchor — bridges head to torso |
| 5 | right_arm | 15 | Right arm — most complex, holds objects |

### Cel Header Format (6 bytes)
```
Byte 0: type(7-6) | width_bytes(3-0)
         width_bytes × 4 = width in multicolor pixels
Byte 1: height in scanlines
Byte 2: x_offset (signed byte, in BYTE units)
Byte 3: y_offset (signed byte, in scanline units)
Byte 4: x_rel (signed, displacement for chaining to next limb)
Byte 5: y_rel (signed, displacement for chaining to next limb)
```

Pixel data follows: 2 bits per pixel, RLE compressed, column-major (bottom to top).
- `00` = transparent (within a data byte: clears screen to background; as RLE zero: skips position entirely)
- `01` = blue/clothing color (receives pattern overlay)
- `10` = black/outline color
- `11` = pink/wild/skin color

### Paint Loop Semantics (from paint.m)
For each non-zero cel byte, the paint loop computes:
```
result = (screen & bluescreen[cel]) | ora_table[cel] | (pattern & mask_blue[cel])
```

Per pixel pair within the byte:
- **00**: clears screen position to background color (NOT transparent)
- **01**: preserves existing screen content, OR's the pattern on top (semi-transparent blend)
- **10**: overwrites with foreground/detail color
- **11**: overwrites with Color RAM/wild color

Zero bytes in the cel data stream trigger `clear_run` — the position is advanced without writing, preserving the existing screen content (true transparency).

## Rendering Pipeline (from C64 source)

### Step 1: Position Chaining (`display_avatar` → `get_cel_xy` → `find_cel_xy`)
All 6 limbs are processed sequentially (0→5). Each limb's position is computed via `find_cel_xy` using the **previous** cel's `x_rel`/`y_rel`:

```
if (previous cel's x_rel == 0 AND y_rel == 0):
    ABSOLUTE: cel_x = cel_x_origin, cel_y = cel_y_origin
else:
    RELATIVE: cel_x += x_rel, cel_y -= y_rel
    (x_rel is negated when cel_dx is set, i.e. back view)
```

Results stored in `cx_tab[0..5]` and `cy_tab[0..5]` (byte/scanline units).
Height adjustment: `cy_tab[i] += avatar_height` for limbs 2-5 (upper body only).

### Step 2: Draw Order (`draw_a_limb`)
Drawing uses view-specific order (from animate.m tables):

| View | Draw order (limb indices) | Source |
|------|--------------------------|--------|
| Side | 0, 1, 2, 3, 4, 5 | default (no reordering) |
| Front | 0, 1, 3, 4, 2, 5 | `fv_cels` table |
| Back | 5, 2, 4, 0, 1, 3 | `bv_cels` table |

### Step 3: Cel Positioning (`paint_1`)
For each cel, `paint_1` reads the cel header and computes final screen position:

```
Normal (side/front):
    screen_x = cx_tab[limb] + x_offset          (bytes)
    screen_y = cy_tab[limb] - y_offset           (scanlines)

Reversed (back view, cel_dx set):
    screen_x = cx_tab[limb] + (1 - x_offset - width_bytes)
    screen_y = cy_tab[limb] - y_offset
    (cel image is also horizontally flipped)
```

### Step 4: Head Rendering (`draw_a_limb` for limb 4)
The head is a separate object ("contained object") drawn in two parts:

1. **Head object** (the actual head): positioned at `cx_tab[4], cy_tab[4] - 63`
   - The constant `63` comes directly from animate.m
   - Each head cel uses **absolute positioning** from the head origin
   - `x_rel`/`y_rel` in head cels chain to the **next limb** (head_placeholder), NOT between cels within the same head

2. **Head placeholder** (neck/collar): drawn at `cx_tab[4], cy_tab[4]` via `paint_limb`
   - Controlled by `disk_face` flags from the head's header:
     - Side/front: drawn only if bit 6 (0x40) is set
     - Back: drawn only if bit 7 (0x80) is set
   - Bridges the visual gap between head and torso

### Step 5: Clothing Patterns (`pick_pattern`, `cel_patterns`)
Blue pixels (value `01`) receive a dither pattern from the 16-entry `cel_patterns` table.
Each pattern is 4 bytes (4 scanlines), repeating. Each byte covers 4 MC pixels (2 bits each):
- `00` → preserves underlying content (C64: OR-blend keeps existing screen)
- `01` → clothing color (blue target)
- `10` → detail color (black target)
- `11` → wild color (pink target)

Pattern index 15 (`0x55` = all `01`) is the default "solid clothing" pattern.

Pattern assignment per body zone (from `pattern_for_limb`):
- Limbs 0,1 → LEG pattern
- Limbs 2,5 → ARM pattern
- Limb 3 → TORSO pattern
- Limb 4 → FACE/HAIR pattern

In the game, patterns were applied using **spray-on body color** objects (bottle.m).
Each spray can displayed its pattern on the bottle body, and players could change
clothing patterns by pointing the cursor at a body zone and choosing DO.

Customization byte layout:
- `Custom1`: `LLLLTTTT` — L=leg pattern(0-15), T=torso pattern(0-15)
- `Custom2`: `AAAA0000` — A=arm pattern(0-15)
- Head orientation: `xPPPPxxx` — P=hair pattern(0-15)

## Animation System

### Start/End Tables (from Avatar.bin)
Each limb has a `start_end` table mapping graphic states to frame ranges:
```
start_end[graphic_state * 2]     = start_frame (bit 7 = cycle flag)
start_end[graphic_state * 2 + 1] = end_frame
```
- **Cycle flag (0x80)**: animation loops continuously (walk, beanie propeller)
- **No cycle**: animation plays once (point, bend)

### Walk Animation
Walk choreography sets all limbs to graphic state 1. From the start_end tables:
- **legs_right**: 4-frame cycle (frames 1-4), cels 0,1,2,3
- **legs_left**: 4-frame cycle (frames 1-4), cels 0,1,2,3
- **left_arm**: 8-frame cycle (frames 1-8), arm swing with hidden frames
- **right_arm**: 8-frame cycle (frames 1-8), arm swing
- **torso**: stays at state 0 (no change)

The simulator uses an 8-frame walk (LCM of 4-frame legs and 8-frame arms).
Back walk adds legs_left overlay cycling through states 1-4.

### Animated Heads
Some heads have cycling start_end entries (bit 7 set):
- **mbeany0/fbeany0**: 4-frame propeller spin (side), 4-frame (front), 4-frame (back)
- **cyclops0**: 3-frame eye animation (front only)
- **robot0**: 2-frame light blink (side/front)
- **fhead/head8**: 2-frame cycling (side/front)

### Timing
All animations run at ~6 fps (167ms per frame), matching the C64's PAL 50Hz VBlank timing with ~8 VBlanks per render cycle.

## Head System

### Per-Head Configuration (head_config.json)
Extracted from 169 C64 head `.m` source files by `tools/extract_head_data.py`:

```
disk_face flags (byte 1 of header):
  bit 7 (0x80): has back overlay — draw head_placeholder in back view
  bit 6 (0x40): has face overlay — draw head_placeholder in side/front view
  bit 5 (0x20): no-bend flag

start_end table (8 bytes):
  [side_start, side_end, front_start, front_end,
   unused_start, unused_end, back_start, back_end]

  C64 facing values: 0=side, 1=front, 3=back
  Index = facing * 2
  Bit 7 of start byte = cycle flag
```

### disk_face Distribution
| Flag | Count | Meaning |
|------|-------|---------|
| 0x00 | 109 | No overlay (largest group) |
| 0x80 | 20 | Back overlay only |
| 0x40 | 21 | Face overlay only |
| 0xC0 | 15 | Both overlays |
| 0xA0 | 3 | Back overlay + no-bend |
| 0x20 | 1 | No-bend only |

### Head Cel Positioning
Each head cel uses **absolute positioning** from the head origin:
```
headOrigin = (cx_tab[4], cy_tab[4] - 63)
celDrawX = BASE_X + (headOrigin.x + cel.x_offset) * BYTE_PX
celDrawY = BASE_Y + (headOrigin.y - cel.y_offset) * SCALE
```

Multi-cel heads (e.g., mbeany0 with head + propeller) draw each cel independently from the same head origin. The `x_rel`/`y_rel` values in head cels are for chaining to the head_placeholder limb, not for intra-head positioning.

## Coordinate System

### C64 Units
- **X**: byte columns (0-39). 1 byte = 4 multicolor pixels = 8 screen pixels.
- **Y**: scanlines (0-199). 1 unit = 1 pixel. Y increases downward.
- Avatar origin: bottom-center of feet.

### Simulator Mapping
```
display_x = BASE_X + (cx_tab[limb] + x_offset) × BYTE_PX
display_y = BASE_Y + (cy_tab[limb] - y_offset) × SCALE

where:
    BYTE_PX = 8 × SCALE = 32    (each byte = 8 PNG pixels × 4 scale)
    SCALE = 4                    (each PNG pixel = 4 display pixels)
```

Canvas uses dynamic centering: avatar is rendered to an offscreen canvas,
bounding box is computed, then centered in the visible canvas. This eliminates
hardcoded BASE_X/BASE_Y brittleness for different head sizes.

## Source Palettes

### Body PNGs (tools/decode_avatar_bin.py)
Pure emulated colors:
- `01` pixels → `(0, 0, 255)` blue
- `10` pixels → `(0, 0, 0)` black
- `11` pixels → `(255, 85, 255)` pink

### Head PNGs (tools/habitat_renderer.py)
May use CRT-attenuated colors if rendered with `--palette`:
- `01` pixels → `(49, 40, 147)` CRT blue
- `10` pixels → `(0, 0, 0)` black
- `11` pixels → `(169, 111, 99)` CRT pink

The simulator's `matchPixelColor` function matches BOTH palettes (tolerance 40 per channel).

## File Structure
```
index.html                          Main simulator (single-file static web app)
habitat_images_final/
  body/                             51 body cel PNGs + body_manifest.json
  heads/                            510 head cel PNGs + heads_manifest.json
                                    + head_config.json (per-head C64 config)
  props/                            Prop object PNGs
tools/
  Avatar.bin                        Original avatar binary (3442 bytes)
  decode_avatar_bin.py              Avatar.bin decoder → body cel PNGs + manifest
  habitat_renderer.py               Head .m file renderer → head cel PNGs + manifest
  extract_head_data.py              Head .m files → head_config.json
NOTES.md                            This file
```

The app is a purely static web application. The Python scripts in `tools/` are
offline asset generators that run once to produce the PNGs and JSON manifests.
The deployable app is just `index.html` + `habitat_images_final/`.

## References
- [Original Habitat source](https://github.com/Museum-of-Art-and-Digital-Entertainment/habitat) — C64 6502 assembly
- [NeoHabitat](https://github.com/frandallfarmer/neohabitat) — Open source Habitat server revival
- [Habitat Chronicles](https://web.stanford.edu/class/history34q/readings/Virtual_Worlds/LucasacfilmHabitat.html) — Design paper by Morningstar & Farmer
- [The Habitat Avatar Handbook](https://frandallfarmer.github.io/neohabitat-doc/docs/Avatar%20Handbook.html) — Original player documentation
