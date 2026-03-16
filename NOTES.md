# Habitat Avatar Simulator - Project Notes

## Overview
A web-based simulator for exploring and combining avatar possibilities from Lucasfilm's Habitat (1986), the first graphical MMO virtual world. The simulator faithfully reconstructs the avatar assembly system using decoded original game assets.

## Avatar Structure

### Body Composition (from Avatar.bin)
The avatar body consists of 6 limbs decoded from `Avatar.bin`:
- **Limb 0 - legs_right**: Primary legs (22 states, 15 cels) - includes side walk, front stand/walk, sitting
- **Limb 1 - legs_left**: Secondary leg detail (5 states, 4 cels) - visible in side walk and front views
- **Limb 2 - left_arm**: Left arm (13 states, 7 cels) - hidden in side view, visible front/back
- **Limb 3 - torso**: Body torso (8 states, 6 cels) - side, front, and back variants
- **Limb 4 - head_placeholder**: Anchor for head attachment (4 states, 4 cels)
- **Limb 5 - right_arm**: Right arm (80 states, 15 cels) - most complex limb with many poses

### Cel Format
Each cel has a 6-byte header:
- Byte 0: type(7-6) | width_bytes(3-0) - width in bytes, multiply by 4 for native pixels
- Byte 1: height in scanlines
- Byte 2: x_offset (signed, in byte units = 4 native pixels)
- Byte 3: y_offset (signed, distance from feet to cel top)
- Byte 4-5: x_rel, y_rel (displacement to next cel in chain)

Pixel data: 2 bits per pixel, RLE compressed, column-major order (bottom to top)
- 00 = transparent
- 01 = outline (black)
- 10 = foreground color
- 11 = wild/pattern color

### Coordinate System
- Origin at avatar's feet
- x_offset: 1 unit = 4 native pixels = 8 stretched pixels (after 2x C64 aspect correction)
- y_offset: distance upward from feet to top of cel
- Cel bottom position: y_offset - height (should be ~0 for ground-touching cels)

## Choreography (State Mappings)

### Key State Indices for legs_right
| States | Cels | Usage |
|--------|------|-------|
| 0-4 | 4,0,1,2,3 | Side view: standing + 4 walk frames |
| 5-6 | 7,8 | Special low positions |
| 7-11 | 5,6,6,6,6 | Sitting/mounted (y_offset=41-45, floating) |
| 16 | 13 | **Front standing** (symmetric, y_off=24, touches ground) |
| 17-20 | 9,10,11,12 | **Front/back walking** (y_off=23, touches ground) |

### Torso States
- States 0-1: Side view (cel 0, cel 1)
- State 6: Front torso (cel 4, 24x19, narrower)
- State 7: Back torso (cel 5, 24x19, back details visible)

## Head System

### Structure
- 167 head types total (8 player-selectable at character creation)
- Each head has 1-7 cels (data_a through data_g)
- gr_state bitmasks control which cels show per view state
- Some heads have animation (robot0, cyclops0, mbeany0, fbeany0)

### View State Mapping
- State 0: Side view
- State 1: Front view
- State 2: Back view
- State 3: Frown/alternate expression

### Head Positioning
Head images are positioned relative to head_placeholder anchor cels:
- Side: x_offset=2, y_offset=58 (placeholder cel 0)
- Front: x_offset=-1, y_offset=57 (placeholder cel 1)
- Back: x_offset=-1, y_offset=62 (placeholder cel 2)

## Source Palettes

### Body PNGs (from decode_avatar_bin.py)
Decoded using C64 Pepto palette:
- Outline: #000000 (black)
- Foreground: #352879 (C64 blue, index 6)
- Wild: #6C5EB5 (C64 light blue, index 14)

### Head PNGs (from habitat_renderer.py)
Decoded using converter defaults:
- Outline: #000000 (black)
- Foreground: #0000FF (pure blue)
- Wild: #FF55FF (pink)

The simulator recolors both at runtime to match the selected C64 palette.

## Known Limitations
- Head cel offset metadata (x_offset, y_offset from .m file headers) was not preserved during PNG conversion, so heads are centered heuristically on the placeholder anchor
- Some heads with complex multi-cel compositions may not align perfectly in all views
- The front/back walk animation uses the same leg cels for both views (legs look similar from front and back)
- Wave and point poses only have side-view arm variants; front/back use standing arm poses

## File Structure
```
index.html                          - Main simulator (single-file web app)
Avatar.bin                          - Original avatar binary (3442 bytes)
decode_avatar_bin.py                - Avatar.bin decoder -> body cel PNGs
habitat_renderer.py                 - .m source file renderer -> head/prop PNGs
habitat_images_final/body/          - 51 decoded body cel PNGs + manifest
habitat_images_final/heads/         - 510 head cel PNGs
```

## References
- [NeoHabitat](https://github.com/Museum-of-Art-and-Digital-Entertainment/habitat) - Open source Habitat server
- [Habitat Chronicles](https://web.stanford.edu/class/history34q/readings/Virtual_Worlds/LucasacfilmHabitat.html) - Original design paper by Morningstar & Farmer
