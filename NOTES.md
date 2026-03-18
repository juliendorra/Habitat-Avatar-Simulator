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
All 6 limbs are processed sequentially (0→5). The algorithm maintains a **running origin** (`cel_x_origin`, `cel_y_origin`) that is updated after each drawn limb.

For each limb, `get_cel_xy` does:
```
1. Load: cel_x = cel_x_origin, cel_y = cel_y_origin
2. Call find_cel_xy (uses PREVIOUS limb's x_rel/y_rel):
   if (previous x_rel == 0 AND y_rel == 0):
       ABSOLUTE: cel_x stays as cel_x_origin (no change)
   else:
       RELATIVE: cel_x = cel_x_origin + x_rel   ← NOTE: added to ORIGIN, not previous cel_x!
                 cel_y = cel_y_origin - y_rel
       (x_rel is negated when cel_dx is set, i.e. back view)
3. Save: cel_x_origin = cel_x  (origin now tracks the new position)
```

**Critical detail for NULL limbs**: when a limb is not drawn (cel 255), `get_cel_loc_addr` is never called, so `cel_x_rel`/`cel_y_rel` **retain their values** from the previous limb. This means x_rel/y_rel propagate through chains of null limbs. For example, in side view standing, legs_right sets x_rel=0/y_rel=-1, and these persist through null legs_left and null left_arm to affect the torso's positioning.

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

### Choreography (chore.m / Avatar.bin)
The choreography system drives all avatar animation. The flow in `new_chore`:

1. **Clear**: all 6 limbs' `cel_state` set to 0 (= gs0 = side standing)
2. **Apply action**: read choreography bytes for the requested action. Each byte encodes `(limb << 4) | graphic_state`, with bit 7 marking the last entry. Special case: limb 6 maps to right_arm (limb 5) with state + 16.
3. **Set facing**: the action determines the view — `stand_front`, `walk_front` → facing=1; `stand_back`, `walk_back` → facing=3; all others → facing=0.

**Critical discovery**: `AV_ACT_init` is action 0 (index 0 in chore_index), which shifts all other actions by 1:
```
AV_ACT_init       = 0x80 + 0   → index 0
AV_ACT_stand      = 0x80 + 1   → index 1
AV_ACT_walk       = 0x80 + 2   → index 2
AV_ACT_bend_over  = 0x80 + 6   → index 6
AV_ACT_wave       = 0x80 + 13  → index 13
AV_ACT_stand_front= 0x80 + 18  → index 18
```
Missing this offset caused every choreography to use the wrong data.

**Front/back view actions are COMPLETE choreographies**, not overlays:
- `stand_front` sets ALL 5 active limbs: legs_right=gs6, left_arm=gs3, torso=gs4, head_placeholder=gs1, right_arm=gs10
- `walk_front` sets ALL limbs: legs_right=gs7, left_arm=gs2, torso=gs4, head_placeholder=gs1, right_arm=gs11
- `walk_back` also sets legs_left=gs1 (back walk overlay)

The simulator's `initAnimAction` mirrors this exactly: clear all to gs0, then apply the single correct action.

### Start/End Tables (from Avatar.bin)
Each limb has a `start_end` table mapping graphic states to frame ranges:
```
start_end[graphic_state * 2]     = start_frame (bit 7 = cycle flag)
start_end[graphic_state * 2 + 1] = end_frame
```
- **Cycle flag (0x80)**: animation loops continuously (walk, beanie propeller)
- **No cycle**: animation plays once and holds at end frame (point, bend)

### Key Choreography Actions
| Action | Sets | Notes |
|--------|------|-------|
| `stand` | legs_r=gs0, r_arm=gs0 | Side standing (minimal — most limbs already gs0) |
| `walk` | legs_r=gs1, l_arm=gs1, r_arm=gs1 | Side walk — sets gs1 for all locomotion limbs |
| `bend_over` | torso=gs2, r_arm=gs2 | Torso bends, arm reaches (gs2 = frames 9→10) |
| `bend_back` | torso=gs3, r_arm=gs3 | Torso unbends |
| `wave` | r_arm=gs9 | Wave gesture (gs9 = frames 31→35) |
| `point` | r_arm=gs5 | Point gesture (gs5 = frames 13→15) |
| `stand_front` | all 5 limbs | Complete front-facing standing |
| `walk_front` | all 6 limbs | Complete front-facing walk cycle |
| `walk_back` | all 6 limbs | Complete back-facing walk cycle (includes legs_left) |

### Walk Animation
The `walk` action sets gs1 for legs_right, left_arm, and right_arm:
- **legs_right gs1**: 4-frame cycle (frames 1-4), cels 0,1,2,3
- **left_arm gs1**: 8-frame cycle (frames 1-8), arm swing with hidden frames
- **right_arm gs1**: 8-frame cycle (frames 1-8), arm swing
- **torso**: stays at gs0 (not changed by walk choreography)
- **legs_left**: NOT set by walk choreography — handled separately (gs1 for side walk overlay)

Arms cycle at half the leg rate (8 frames vs 4), creating natural-looking asynchronous limb movement. The walk animation is entirely data-driven through the choreography + start_end tables.

For front/back walk, `walk_front`/`walk_back` are separate complete choreographies:
- **legs_right gs7**: 4-frame cycle with front/back leg cels (9,10,11,12)
- **left_arm gs2**: 4-frame cycle with front arm cels (4,5,6,5)
- **right_arm gs11**: 4-frame cycle with front arm cels (12,13,14,13)

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
Heads are drawn as "contained objects" via `draw_prop`. The head origin is:
```
headOrigin = (cx_tab[4], cy_tab[4] - 63)
```

**Multi-cel heads chain via x_rel/y_rel** (like body limbs). The C64 `draw_prop` initializes `cel_x_rel=0, cel_y_rel=0` before the first cel. For each subsequent cel, `find_cel_xy` uses the PREVIOUS cel's x_rel/y_rel:
```
Cel A (base head): drawn at headOrigin + x_offset. Sets x_rel=2 for next.
Cel D (propeller): find_cel_xy sees x_rel=2 → chains: cel_x = headOrigin.x + 2
                   Then drawn at (headOrigin.x + 2 + cel_D.x_offset)
```
This was initially implemented wrong as absolute positioning for all cels, causing propellers and multi-part heads to be misaligned.

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

Canvas uses fixed BASE_X/BASE_Y positioning with the canvas sized to accommodate
the tallest heads. BASE_X is placed slightly left of center, BASE_Y near the
bottom with room for feet.

## Lessons Learned (False Assumptions Corrected)

### 1. x_rel adds to ORIGIN, not to previous cel_x
**Wrong**: `cel_x = previous_cel_x + x_rel` (running accumulation)
**Right**: `cel_x = cel_x_origin + x_rel` (origin is loaded first, then rel added)
The C64 `get_cel_xy` explicitly loads `cel_x = cel_x_origin` before calling `find_cel_xy`. The origin is then updated to the result. This is subtly different from accumulating — the origin tracks the running position, and each step adds rel to the ORIGIN, not to the previous result.

### 2. NULL limbs retain x_rel/y_rel (don't reset to 0)
**Wrong**: null limbs reset `cel_x_rel = 0, cel_y_rel = 0`
**Right**: null limbs skip `get_cel_loc_addr`, so x_rel/y_rel from the PREVIOUS drawn limb persist
This matters for side-view standing: legs_right sets y_rel=-1, which persists through null legs_left and null left_arm, affecting the torso's Y position by 1 scanline.

### 3. Head cels chain via x_rel/y_rel (not absolute)
**Wrong**: each head cel uses absolute positioning from the head origin
**Right**: head cels chain like body limbs via `draw_prop`, using `find_cel_xy` with initialized x_rel=0/y_rel=0 for the first cel, then chaining
This fixes multi-part heads like mbeany0 (head + propeller) where cel A's x_rel=2 shifts cel D's position.

### 4. x_offset units are bytes, not MC pixels
**Wrong** (early attempt): x_offset multiplied by 2 (treating as MC pixels)
**Right**: x_offset is in the same byte-column units as cel_x, matching width_bytes. In `paint_1`, x_offset is added directly to `cel_x` to compute `screen_x`, and screen_x indexes 8-pixel-wide character cells.

### 5. Pattern value 00 preserves screen (not background fill)
**Wrong**: pattern pixel 00 fills with canvas background color
**Right**: the paint formula `(screen & bluescreen) | ora_table | (pattern & mask_blue)` evaluates to `screen` when pattern=00, meaning existing screen content shows through. This is transparent compositing, not background fill.

### 6. The choreography system sets graphic states, not frame indices
**Wrong**: pose frames directly set LIMB_STATES indices
**Right**: the choreography byte encodes `(limb << 4) | graphic_state`, and each graphic_state maps through the limb's start_end table to a frame range. The animation system then cycles through that range.

### 7. Avatar.bin contains choreography data (not just cel data)
The first 4 bytes of Avatar.bin are offsets to `chore_index` and `chore_tables`. These tables define all avatar actions (stand, walk, bend, wave, point, etc.) as sets of `(limb, graphic_state)` pairs. Bit 7 of each byte marks the last entry in the action.

### 8. AV_ACT_init (action 0) shifts all choreography indices
**Wrong**: assumed action 0 = stand, action 1 = walk
**Right**: AV_ACT_init (0x80+0) is action 0. AV_ACT_stand is 0x80+1 (index 1), AV_ACT_walk is 0x80+2 (index 2), etc. Missing this offset caused EVERY action to read the wrong choreography bytes — walk used stand's data (gs0 for everything instead of gs1 for locomotion), bend used walk's data, etc. This was the root cause of most animation bugs.

### 9. Front/back actions are complete choreographies, not overlays
**Wrong**: apply stand_front as a partial overlay on top of stand, then add walk-specific overrides
**Right**: stand_front, walk_front, walk_back etc. set ALL relevant limbs. They are complete choreographies designed to be applied after clearing all states to gs0. No manual "facing defaults" or "walk movement system overrides" needed.

### 10. Limb 6 in choreography bytes maps to right_arm with state+16
**Wrong**: limb 6 treated as invalid/ignored
**Right**: the C64 new_chore code explicitly handles limb 6 → maps to limb 5 (right_arm) with state += 16, allowing right_arm graphic states above 15 (up to gs23 for complex arm sequences like operate, shoot, knife).

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
  extract_avatar_animations.py      Avatar.bin → avatar_animations.json (choreography + start_end)
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
