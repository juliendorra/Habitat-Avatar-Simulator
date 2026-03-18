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
| `sources/c64/Images/Avatar.bin` | Binary body cel data (3442 bytes) |
| `sources/c64/Images/Heads/*.m` | Head cel data as macro assembler source |

## Avatar Body Structure

### 6 Limbs (from Avatar.bin)
The avatar body is composed of exactly 6 limbs, always processed in index order 0-5:

| Index | Name | Cels | Role |
|-------|------|------|------|
| 0 | legs_right | 15 | Primary legs — walk cycle, standing, sitting |
| 1 | legs_left | 4 | Secondary leg — visible during walk stride |
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
Byte 3: y_offset (signed byte, in scanline units, distance from bottom)
Byte 4: x_rel (signed, displacement for chaining to next cel)
Byte 5: y_rel (signed, displacement for chaining to next cel)
```

Pixel data follows: 2 bits per pixel, RLE compressed, column-major (bottom to top).
- `00` = transparent
- `01` = blue/clothing color (receives pattern overlay)
- `10` = black/outline color
- `11` = pink/wild/skin color

## Rendering Pipeline (from C64 source)

### Step 1: Position Chaining (`display_avatar` → `get_cel_xy` → `find_cel_xy`)
All 6 limbs are processed sequentially (0→5). Each limb's position is computed via `find_cel_xy`:

```
if (previous cel's x_rel == 0 AND y_rel == 0):
    use ABSOLUTE position (revert to origin)
else:
    RELATIVE: cel_x = origin + x_rel, cel_y = origin - y_rel
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
   - `draw_contained_object` recursively draws the head's own cels
   - Head cels have their own x_offset/y_offset applied by paint_1

2. **Head placeholder** (neck/collar): drawn at `cx_tab[4], cy_tab[4]` via `paint_limb`
   - Bridges the visual gap between head and torso

### Step 5: Pattern Application (`pick_pattern`, `cel_patterns`)
Blue pixels (value `01`) receive a dither pattern from the 16-entry `cel_patterns` table.
Each pattern is 4 bytes (4 scanlines), repeating. Each byte covers 4 MC pixels (2 bits each):
- `00` → transparent
- `01` → clothing color (blue target)
- `10` → detail color (black target)
- `11` → wild color (pink target)

Pattern assignment per body zone (from `pattern_for_limb`):
- Limbs 0,1 → LEG pattern
- Limbs 2,5 → ARM pattern
- Limb 3 → TORSO pattern
- Limb 4 → FACE/HAIR pattern

Customization byte layout:
- `Custom1`: `LLLLTTTT` — L=leg pattern(0-15), T=torso pattern(0-15)
- `Custom2`: `AAAA0000` — A=arm pattern(0-15)
- Head orientation: `xPPPPxxx` — P=hair pattern(0-15)

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
    BASE_X = 170                 (avatar origin X on 400px canvas)
    BASE_Y = 280                 (avatar origin Y / foot line)
```

## Choreography (State Machine)

### State Index → Cel Number
Each limb has a states array that maps state indices to cel numbers.
State 255 = not drawn. The choreography system sets state indices per limb.

### Key Pose Assignments

**Side view:**
- Standing: legs_right=0, torso=0, right_arm=0 (cel 11)
- Walk cycle: 4 frames alternating leg stride cels
- Bend: torso states 0→2→3 (standing→half→full), right_arm 0→3→5

**Front/back views:**
- Use front-specific torso cels (state 7→cel 5 = front, state 6→cel 4 = back)
- Left arm uses cels 4-6 (x_offset ≥ 0, viewer's right side)
- Right arm uses cels 12-14 (x_offset < 0, viewer's left side)
- Back view applies cel_dx reversal (flips all X coordinates)

### Female Torso
From animate.m: if `avatar_style == 0` and `cel_number == 3` (torso) and orientation bit 7 is set (female), the animation state advances by 1 (using the next cel).

## Head System

### Structure
- 167 head types (8 selectable at character creation)
- Each head: 1-7 cels (data_a through data_g)
- `gr_state` bitmasks control which cels are visible per view state
- View states: 0=side, 1=front, 2=back, 3=frown/alternate

### Head Data Format
```
Header:
  Byte 0: animation_type | num_states
  Byte 1: cel-to-draw bitmask (which cels exist)
  Byte 2: offset to start/end table
  Byte 3: containment flags
  Bytes 4-6: object-level x/y offsets

Per-state: cel bitmask (which cels visible in this state)
Then: word-sized offsets to each cel's data
Each cel: 6-byte header (same format as body) + RLE pixel data
```

### Head Positioning
Head origin = `cx_tab[4], cy_tab[4] - 63` (from animate.m).
Then each head cel's own x_offset/y_offset positions it relative to this origin via paint_1.

The head_placeholder (limb 4) provides the attachment point:
| State | x_offset | y_offset | View |
|-------|----------|----------|------|
| 0 | 2 | 58 | Side |
| 1 | -1 | 57 | Front |
| 2 | -1 | 62 | Back |
| 3 | 2 | 59 | Frown |

## Source Palettes

### Body PNGs (decode_avatar_bin.py)
Pure emulated colors:
- `01` pixels → `(0, 0, 255)` blue
- `10` pixels → `(0, 0, 0)` black
- `11` pixels → `(255, 85, 255)` pink

### Head PNGs (habitat_renderer.py)
May use CRT-attenuated colors if rendered with `--palette`:
- `01` pixels → `(49, 40, 147)` CRT blue
- `10` pixels → `(0, 0, 0)` black
- `11` pixels → `(169, 111, 99)` CRT pink

The simulator's recolor system matches BOTH palettes (tolerance 40 per channel).

## File Structure
```
index.html                          Main simulator (single-file web app)
Avatar.bin                          Original avatar binary (3442 bytes)
decode_avatar_bin.py                Avatar.bin decoder → body cel PNGs
habitat_renderer.py                 Head .m file renderer → head cel PNGs
habitat_images_final/body/          51 body cel PNGs + body_manifest.json
habitat_images_final/heads/         510 head cel PNGs + heads_manifest.json
NOTES.md                            This file
```

## References
- [Original Habitat source](https://github.com/Museum-of-Art-and-Digital-Entertainment/habitat) — C64 6502 assembly
- [NeoHabitat](https://github.com/frandallfarmer/neohabitat) — Open source Habitat server revival
- [Habitat Chronicles](https://web.stanford.edu/class/history34q/readings/Virtual_Worlds/LucasacfilmHabitat.html) — Design paper by Morningstar & Farmer
