#!/usr/bin/env python3
"""Extract choreography and animation data from Avatar.bin.

Produces avatar_animations.json with:
- limb_states: frame→cel mapping per limb (LIMB_STATES)
- start_end: graphic_state→frame_range per limb
- choreography: action→limb_assignments
- draw_order: per-view limb draw order
- constants: head_cel_number, cels_affected_by_height, etc.

This data drives the simulator's animation engine, replacing hardcoded POSES.
"""

import json
import struct
import os


def extract(bin_path, out_path):
    with open(bin_path, 'rb') as f:
        data = f.read()

    # Header: 2-word offsets to chore_index and chore_tables
    chore_idx_off = data[0] | (data[1] << 8)
    chore_tab_off = data[2] | (data[3] << 8)

    # Limb data
    limb_names = ['legs_right', 'legs_left', 'left_arm', 'torso', 'head_placeholder', 'right_arm']
    limb_offsets = [0x002D, 0x05A4, 0x065E, 0x07A1, 0x08C3, 0x0941]

    limb_states = {}
    start_end_tables = {}

    for i, (name, off) in enumerate(zip(limb_names, limb_offsets)):
        header = data[off]
        num_states = (header & 0x7F) + 1

        # Read frame→cel mapping
        states = [data[off + 3 + s] for s in range(num_states)]
        limb_states[name] = states

        # Find start_end table (after cel offset table)
        unique_cels = sorted(set(s for s in states if s != 0xFF))
        num_cels = max(unique_cels) + 1 if unique_cels else 0
        cel_table_off = off + 3 + num_states
        cel_table_end = cel_table_off + num_cels * 2

        # Parse start_end pairs until we hit clearly invalid data
        # Right_arm has up to 20 graphic states, so allow up to 25
        se = []
        max_gs = 25
        for gs in range(max_gs):
            pos = cel_table_end + gs * 2
            if pos + 1 >= len(data):
                break
            start_raw = data[pos]
            end_raw = data[pos + 1]
            start = start_raw & 0x7F
            cycle = bool(start_raw & 0x80)

            # Validate: start and end must be valid frame indices
            if start >= num_states or end_raw >= num_states:
                break

            se.append({
                'start': start,
                'end': end_raw,
                'cycle': cycle,
            })

        start_end_tables[name] = se

    # Choreography: action→limb assignments
    # Action numbering from equates.m: AV_ACT_init=0x80+0, AV_ACT_stand=0x80+1, etc.
    # The chore_index uses (action & 0x7F) as the table index.
    action_names = [
        'init',         #  0: AV_ACT_init (0x80)
        'stand',        #  1: AV_ACT_stand (0x81)
        'walk',         #  2: AV_ACT_walk (0x82)
        'hand_back',    #  3: AV_ACT_hand_back (0x83)
        'sit_floor',    #  4: AV_ACT_sit_floor (0x84)
        'sit_chair',    #  5: AV_ACT_sit_chair (0x85)
        'bend_over',    #  6: AV_ACT_bend_over (0x86)
        'bend_back',    #  7: AV_ACT_bend_back (0x87)
        'point',        #  8: AV_ACT_point (0x88)
        'throw',        #  9: AV_ACT_throw (0x89)
        'get_shot',     # 10: AV_ACT_get_shot (0x8A)
        'jump',         # 11: AV_ACT_jump (0x8B)
        'punch',        # 12: AV_ACT_punch (0x8C)
        'wave',         # 13: AV_ACT_wave (0x8D)
        'frown',        # 14: AV_ACT_frown (0x8E)
        'stand_back',   # 15: AV_ACT_stand_back (0x8F)
        'walk_front',   # 16: AV_ACT_walk_front (0x90)
        'walk_back',    # 17: AV_ACT_walk_back (0x91)
        'stand_front',  # 18: AV_ACT_stand_front (0x92)
        'unpocket',     # 19: AV_ACT_unpocket (0x93)
        'gimme',        # 20: AV_ACT_gimme (0x94)
        'knife',        # 21: AV_ACT_knife (0x95)
        'arm_get',      # 22: AV_ACT_arm_get (0x96)
        'hand_out',     # 23: AV_ACT_hand_out (0x97)
        'operate',      # 24: AV_ACT_operate (0x98)
        'arm_back',     # 25: AV_ACT_arm_back (0x99)
        'shoot1',       # 26: AV_ACT_shoot1 (0x9A)
        'shoot2',       # 27: AV_ACT_shoot2 (0x9B)
        'nop',          # 28: AV_ACT_nop (0x9C)
        'sit_front',    # 29: AV_ACT_sit_front (0x9D)
    ]

    choreography = {}
    num_actions = min(len(action_names), chore_tab_off - chore_idx_off)

    for act_num in range(num_actions):
        tab_offset = data[chore_idx_off + act_num]
        abs_offset = chore_tab_off + tab_offset

        entries = {}
        i = abs_offset
        while i < len(data):
            b = data[i]
            raw = b & 0x7F              # mask off stop bit
            limb_idx = (raw >> 4) & 0x07  # bits 6-4
            gs = raw & 0x0F              # bits 3-0
            is_last = bool(b & 0x80)     # bit 7

            # C64 special case: limb 6 → right_arm (limb 5) with state + 16
            if limb_idx == 6:
                limb_idx = 5
                gs += 16

            limb_name = limb_names[limb_idx] if limb_idx < 6 else f'limb{limb_idx}'
            entries[limb_name] = gs
            i += 1
            if is_last:
                break

        name = action_names[act_num]
        choreography[name] = entries

    # Constants from animate.m
    result = {
        'limb_names': limb_names,
        'limb_states': limb_states,
        'start_end': start_end_tables,
        'choreography': choreography,
        'draw_order': {
            'side': [0, 1, 2, 3, 4, 5],          # natural order
            'front': [0, 1, 3, 4, 2, 5],          # fv_cels: 0,1,3,4,2,5
            'back': [5, 2, 4, 0, 1, 3],           # bv_cels: 5,2,4,0,1,3
        },
        'head_cel_number': 4,
        'cels_affected_by_height': [0, 0, 1, 1, 1, 1],
        'pattern_for_limb': [0, 0, 2, 1, 3, 2],   # AVATAR_LEG=0, TORSO=1, ARM=2, FACE=3
        'head_y_constant': 63,                      # sbc #63 in draw_a_limb
    }

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f'Saved to {out_path}')

    # Summary
    print(f'\nLimb states:')
    for name, states in limb_states.items():
        print(f'  {name}: {len(states)} frames')

    print(f'\nStart/end tables:')
    for name, se in start_end_tables.items():
        print(f'  {name}: {len(se)} graphic states')
        for gs_idx, gs in enumerate(se):
            cels = [limb_states[name][f] for f in range(gs['start'], gs['end'] + 1)
                    if f < len(limb_states[name])]
            flag = ' (cycle)' if gs['cycle'] else ''
            print(f'    gs{gs_idx}: frames {gs["start"]}→{gs["end"]}{flag} → cels {cels}')

    print(f'\nChoreography ({len(choreography)} actions):')
    for name, entries in choreography.items():
        limbs = ', '.join(f'{k}=gs{v}' for k, v in entries.items())
        print(f'  {name}: {limbs}')


if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bin_path = os.path.join(script_dir, 'Avatar.bin')
    out_path = os.path.join(script_dir, '..', 'habitat_images_final', 'body', 'avatar_animations.json')
    extract(bin_path, out_path)
