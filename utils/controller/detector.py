#!/usr/bin/env python3
"""
detector.py - Polls joystick devices and produces InputEvents

Adds proper modifier-layer routing AND a global inhibit for base buttons:
- If the global modifier is held:
    * All base-layer **buttons** (bindings without :M) are ignored.
    * Modified-layer (:M) bindings work (and take priority as before).
- If the modifier is not held:
    * Modified-layer bindings are ignored.
    * Base-layer bindings behave normally.

Axis mappings are unchanged (only base **buttons** are inhibited).
"""

import pygame
from dataclasses import dataclass
from typing import Optional, Tuple, Dict


@dataclass
class InputEvent:
    binding: object   # BindingMap
    pressed: bool     # True for press/active, False for release/inactive
    value: float = 0.0


class InputDetector:
    def __init__(self, log, input_cfg, bindings):
        self.log = log
        self.input_cfg = input_cfg
        self.bindings = bindings
        self.state_cache: Dict[Tuple, bool] = {}
        self._last_mod_on: Optional[bool] = None

        pygame.init()
        pygame.joystick.init()

        # list devices
        self.devices = []
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            js.init()
            try:
                guid = js.get_guid()
            except AttributeError:
                guid = f"index-{i}"
            self.devices.append((i, js, guid))
            self.log.info(
                f"[DEVICE] Joystick {i}: {js.get_name()} "
                f"(GUID={guid}) Buttons={js.get_numbuttons()} Axes={js.get_numaxes()}"
            )

        # Verify bindings point at something we actually have (best-effort)
        for bm in self.bindings:
            ib = bm.input
            match = False
            for idx, js, guid in self.devices:
                if ib.device_guid and str(ib.device_guid).lower() == str(guid).lower():
                    match = True
                    break
                if ib.device_index is not None and ib.device_index == idx:
                    match = True
                    break
            if not match:
                self.log.warning(
                    f"[BINDINGS] No attached device for binding: "
                    f"guid={ib.device_guid} index={ib.device_index} ({bm})"
                )

        # Build quick index so we can prefer MOD vs BASE for the same physical input
        self._index = self._build_index(self.bindings)

    # ------------------------------------------------------------------
    # Index: for each physical input key → {'base': bm|None, 'mod': bm|None}
    # ------------------------------------------------------------------
    @staticmethod
    def _key_for_binding(ib) -> Tuple[Optional[str], Optional[int], str, int]:
        return (ib.device_guid, ib.device_index, ib.input_type, ib.input_id)

    def _build_index(self, maps):
        idx: Dict[Tuple, Dict[str, object]] = {}
        for bm in maps:
            ib = bm.input
            key = self._key_for_binding(ib)
            slot = idx.get(key)
            if slot is None:
                slot = {'base': None, 'mod': None}
                idx[key] = slot
            if ib.modifier_layer:
                slot['mod'] = bm
            else:
                slot['base'] = bm
        return idx

    # ------------------------------------------------------------------
    # Resolve pygame joystick for a given binding input
    # ------------------------------------------------------------------
    def _resolve_device(self, ib):
        """Return pygame joystick for given binding input."""
        for idx, js, guid in self.devices:
            if ib.device_index is not None and ib.device_index == idx:
                return js
            if ib.device_guid and ib.device_guid == guid:
                return js
        return None

    # ------------------------------------------------------------------
    # Global modifier state
    # ------------------------------------------------------------------
    def _modifier_active(self) -> bool:
        """Evaluate the global modifier (button or axis)."""
        ib = getattr(self.input_cfg, "modifier", None)
        if not ib:
            return False

        js = self._resolve_device(ib)
        if not js:
            return False

        try:
            if ib.input_type == "button":
                num = js.get_numbuttons()
                if ib.input_id < 0 or ib.input_id >= num:
                    return False
                return js.get_button(ib.input_id) == 1

            if ib.input_type == "axis":
                num = js.get_numaxes()
                if ib.input_id < 0 or ib.input_id >= num:
                    return False
                val = js.get_axis(ib.input_id)
                thr = ib.threshold if (ib.threshold is not None) else 0.5
                mode = ib.axis_mode or "abs"
                if mode == "pos":
                    return val > thr
                if mode == "neg":
                    return val < -thr
                return abs(val) > thr  # "abs"
        except Exception:
            return False

        return False

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------
    def poll(self):
        """Poll all bindings, return list of InputEvents."""
        pygame.event.pump()
        events = []

        # Check modifier once per poll
        mod_on = self._modifier_active()
        if mod_on != self._last_mod_on:
            self.log.info("[MOD] M -> %s", "ON" if mod_on else "OFF")
            self._last_mod_on = mod_on

        for bm in self.bindings:
            ib = bm.input

            # --------- LAYER GATING ----------
            # If this is a modified-layer binding, ignore unless modifier is on.
            if ib.modifier_layer and not mod_on:
                continue

            # GLOBAL INHIBIT (requested): when modifier is ON, ignore ALL base-layer BUTTONs
            # GLOBAL INHIBIT (buttons + axes): when modifier is ON, ignore ALL base-layer bindings
            if (not ib.modifier_layer) and mod_on:
                continue

            # Previous priority rule (kept for axes): if modifier ON and a :M exists for same input,
            # let :M handle it instead of base.
            if (not ib.modifier_layer) and mod_on and ib.input_type != "button":
                slot = self._index.get(self._key_for_binding(ib))
                if slot and slot.get('mod') is not None:
                    continue

            js = self._resolve_device(ib)
            if not js:
                continue

            # ---------------- BUTTON ----------------
            if ib.input_type == "button":
                num = js.get_numbuttons()
                if ib.input_id < 0 or ib.input_id >= num:
                    if self.input_cfg.debug_inputs:
                        self.log.warning(
                            f"[DETECTOR] Invalid button index {ib.input_id} "
                            f"for device {ib.device_index} (has {num}) binding={bm}"
                        )
                    continue
                state = js.get_button(ib.input_id) == 1

            # ---------------- AXIS-AS-BUTTON ----------------
            elif ib.input_type == "axis" and ib.axis_mode:
                num = js.get_numaxes()
                if ib.input_id < 0 or ib.input_id >= num:
                    if self.input_cfg.debug_inputs:
                        self.log.warning(
                            f"[DETECTOR] Invalid axis index {ib.input_id} "
                            f"for device {ib.device_index} (has {num}) binding={bm}"
                        )
                    continue
                val = js.get_axis(ib.input_id)
                state = False
                if ib.axis_mode == "pos":
                    state = val > (ib.threshold or 0.5)
                elif ib.axis_mode == "neg":
                    state = val < -(ib.threshold or 0.5)
                elif ib.axis_mode == "abs":
                    state = abs(val) > (ib.threshold or 0.5)

            # ---------------- AXIS (continuous) ----------------
            elif ib.input_type == "axis" and not ib.axis_mode:
                num = js.get_numaxes()
                if ib.input_id < 0 or ib.input_id >= num:
                    if self.input_cfg.debug_inputs:
                        self.log.warning(
                            f"[DETECTOR] Invalid axis index {ib.input_id} "
                            f"for device {ib.device_index} (has {num}) binding={bm}"
                        )
                    continue
                val = js.get_axis(ib.input_id)
                # Continuous axis: emit every frame (already layer-gated above)
                events.append(InputEvent(bm, True, value=val))
                continue

            else:
                continue

            # ---------------- DIGITAL EDGE EMIT ----------------
            key = (
                ib.device_index,
                ib.device_guid,
                ib.input_type,
                ib.input_id,
                ib.axis_mode,
                ib.threshold,
                ib.modifier_layer
            )
            prev = self.state_cache.get(key, False)
            if state != prev:
                events.append(InputEvent(bm, state, value=1.0 if state else 0.0))
                self.state_cache[key] = state

        return events
