#!/usr/bin/env python3
"""
detector.py - Polls joystick devices and produces InputEvents
"""

import pygame
from dataclasses import dataclass

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
        self.state_cache = {}
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

        # --- NEW: verify bindings ---
        for bm in self.bindings:
            ib = bm.input
            match = False
            for idx, js, guid in self.devices:
                if ib.device_guid and ib.device_guid.lower() == guid.lower():
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


    def _resolve_device(self, ib):
        """Return pygame joystick for given binding input."""
        for idx, js, guid in self.devices:
            if ib.device_index is not None and ib.device_index == idx:
                return js
            if ib.device_guid and ib.device_guid == guid:
                return js
        return None

    def poll(self):
        """Poll all bindings, return list of InputEvents."""
        pygame.event.pump()
        events = []

        for bm in self.bindings:
            ib = bm.input
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
                events.append(InputEvent(bm, True, value=val))
                continue

            else:
                continue

            # digital (button or axis-as-button): only on edge
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
