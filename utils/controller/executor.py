#!/usr/bin/env python3
"""
executor.py - Executes actions for input events. Supports:
- key presses (single / hold)
- mouse button clicks (single / hold)
- hold-to-scroll mouse wheel with acceleration
- mouse movement from analog axes (relative/absolute)
- centering mouse on window/monitor/virtual screen
- focusing windows
- wiggle toggle
- mouse increment (MouseInc/MouseDec) with acceleration
"""

import ctypes
import time
from ctypes import wintypes as wt

user32 = ctypes.windll.user32


class InputExecutor:
    def __init__(self, log, keymapper, mousecontroller, input_cfg):
        self.log = log
        self.keymapper = keymapper
        self.mousecontroller = mousecontroller
        self.input_cfg = input_cfg

        # axis accumulators
        self.axis_accum = {}
        self._abs_pos = None

        # wheel hold state
        self.wheel_state = {}

        # wiggle state
        self.wiggle_active = input_cfg.wiggle_initially_on
        self.last_wiggle = 0
        self.wiggle_px = input_cfg.wiggle_px
        self.wiggle_ms = input_cfg.wiggle_ms
        self.wiggle_mode = "relative"
        if self.wiggle_active and self.log:
            self.log.info(f"[WIGGLE] initially ON (px={self.wiggle_px}, ms={self.wiggle_ms})")

        self.wiggle_mode = "relative"

        # increment state (per-binding)
        self.increment_state = {}
        self.key_toggle_state = {}
        self.key_toggle_repeat = {}   # tracks repeat timing for toggled keys
    # ---------------------------------------------------------------
    # Event handling
    # ---------------------------------------------------------------
    def handle_event(self, event):
        ib = event.binding.input
        for out in event.binding.outputs:
            if out.type == "key":
                self._exec_key(out, event)

            elif out.type == "mouse_button":
                self._exec_button(out, event)

            elif out.type == "mouse_wheel":
                if event.pressed:
                    self._start_wheel_hold(ib, out)
                else:
                    self._stop_wheel_hold(ib, out)

            elif out.type == "mouse_axis":
                self._exec_axis(out, event)

            elif out.type == "mouse_center" and event.pressed:
                self._exec_center(out)

            elif out.type == "focus_window" and event.pressed:
                self._exec_focus(out)

            elif out.type == "mouse_wiggle" and event.pressed:
                self._toggle_wiggle(out)

            elif out.type == "mouse_increment":
                if event.pressed:
                    self._start_increment(ib, out)
                else:
                    self._stop_increment(ib, out)

    def update(self):
        """Update continuous effects once per frame"""
        self._update_wheels()
        self._update_wiggle()
        self._update_increments()
        self._update_key_toggles()

    # ---------------------------------------------------------------
    # Keys / Buttons
    # ---------------------------------------------------------------
    def _exec_key(self, out, event):
        if out.mode == "single":
            if event.pressed:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[KEY] {out.value} TAP")
                self.keymapper.tap(out.value)

        elif out.mode == "hold":
            if event.pressed:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[KEY] {out.value} DOWN")
                self.keymapper.key_down(out.value)
            else:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[KEY] {out.value} UP")
                self.keymapper.key_up(out.value)
        elif out.mode == "toggle":
            if event.pressed:
                key_id = (
                    out.type,
                    out.value,
                    event.binding.input.device_guid,
                    event.binding.input.input_id,
                )
                state = self.key_toggle_state.get(key_id, False)
                if state:
                    # turn OFF
                    self.keymapper.key_up(out.value)
                    self.key_toggle_state[key_id] = False
                    self.key_toggle_repeat.pop(key_id, None)
                    if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                        self.log.info(f"[KEY] {out.value} TOGGLE OFF")
                else:
                    # turn ON
                    self.keymapper.key_down(out.value)  # optional: initial down
                    self.key_toggle_state[key_id] = True
                    self.key_toggle_repeat[key_id] = time.time()
                    if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                        self.log.info(f"[KEY] {out.value} TOGGLE ON")


    def _exec_button(self, out, event):
        hold_ms = 30
        if out.extra and "hold_ms" in out.extra:
            hold_ms = out.extra["hold_ms"]

        if out.mode == "single":
            if event.pressed:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[BUTTON] Mouse {out.value} CLICK ({hold_ms} ms)")
                self.mousecontroller.click(out.value, hold_ms=hold_ms)

        elif out.mode == "hold":
            if event.pressed:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[BUTTON] Mouse {out.value} DOWN")
                self.mousecontroller.button_down(out.value)
            else:
                if self.input_cfg.debug_inputs or self.input_cfg.log_buttons:
                    self.log.info(f"[BUTTON] Mouse {out.value} UP")
                self.mousecontroller.button_up(out.value)

    # ---------------------------------------------------------------
    # Wheel hold-to-scroll
    # ---------------------------------------------------------------
    def _wheel_key(self, ib, out):
        return (ib.device_index, ib.device_guid, ib.input_type, ib.input_id, out.value)

    def _start_wheel_hold(self, ib, out):
        now = time.time()
        self.wheel_state[self._wheel_key(ib, out)] = {"start": now, "last": now, "out": out}
        if self.input_cfg.debug_inputs:
            self.log.info(f"[INPUT] wheel {out.value} START")
        self.mousecontroller.wheel(out.value)

    def _stop_wheel_hold(self, ib, out):
        key = self._wheel_key(ib, out)
        if key in self.wheel_state:
            if self.input_cfg.debug_inputs:
                self.log.info(f"[INPUT] wheel {key[-1]} STOP")
            del self.wheel_state[key]

    def _update_key_toggles(self):
        if not self.key_toggle_repeat:
            return
        now = time.time()
        for key_id in list(self.key_toggle_repeat.keys()):
            out_value = key_id[1]  # the actual key string
            last_time = self.key_toggle_repeat[key_id]
            if now - last_time >= 0.05:  # repeat every 50 ms
                self.keymapper.tap(out_value)  # send down+up
                self.key_toggle_repeat[key_id] = now

    def _update_wheels(self):
        if not self.wheel_state:
            return
        now = time.time()
        for key, state in list(self.wheel_state.items()):
            out = state["out"]
            init = max(1, int(out.wheel_init or 5))
            vmax = max(init, int(out.wheel_max or 30))
            ramp_ms = max(1, int(out.wheel_accel or 1000))

            start = state["start"]
            last = state["last"]

            elapsed_ms = (now - start) * 1000.0
            if elapsed_ms >= ramp_ms:
                rate = float(vmax)
            else:
                rate = init + (vmax - init) * (elapsed_ms / ramp_ms)

            interval = 1.0 / max(1e-6, rate)
            while now - last >= interval:
                self.mousecontroller.wheel(out.value)
                last += interval
                if self.input_cfg.debug_inputs:
                    self.log.info(f"[INPUT] wheel {out.value} TICK (rate={rate:.1f}/s)")
            state["last"] = last

    # ---------------------------------------------------------------
    # Axis handling
    # ---------------------------------------------------------------
    def _exec_axis(self, out, event):
        dev_idx   = event.binding.input.device_index
        guid      = event.binding.input.device_guid
        axis_id   = event.binding.input.input_id
        axis_name = out.value  # "x" or "y"
        key = (dev_idx, guid, axis_id, axis_name)

        value = event.value
        if abs(value) < self.input_cfg.axis_deadzone:
            value = 0.0
            return

        velocity = value * self.input_cfg.axis_speed
        dt = 1.0 / max(1, self.input_cfg.axis_poll_hz)

        delta = velocity * dt
        accum = self.axis_accum.get(key, 0.0) + delta
        step = int(accum)
        self.axis_accum[key] = accum - step

        if step != 0:
            if self.input_cfg.axis_mode == "relative":
                if axis_name == "x":
                    self.mousecontroller.move_relative(step, 0)
                else:
                    self.mousecontroller.move_relative(0, step)
            else:  # absolute
                if self._abs_pos is None:
                    pt = wt.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    self._abs_pos = [pt.x, pt.y]

                if axis_name == "x":
                    self._abs_pos[0] += step
                else:
                    self._abs_pos[1] += step

                x0 = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
                y0 = user32.GetSystemMetrics(77)
                w  = user32.GetSystemMetrics(78)
                h  = user32.GetSystemMetrics(79)
                self._abs_pos[0] = max(x0, min(x0 + w - 1, self._abs_pos[0]))
                self._abs_pos[1] = max(y0, min(y0 + h - 1, self._abs_pos[1]))
                self.mousecontroller.set_position_pixels(self._abs_pos[0], self._abs_pos[1])

        if self.input_cfg.debug_inputs or self.input_cfg.log_axes:
            self.log.info(
                f"[AXIS] {axis_name.upper()} val={value:.3f} vel={velocity:.1f} step={step}"
            )

    # ---------------------------------------------------------------
    # CenterMouse
    # ---------------------------------------------------------------
    def _exec_center(self, out):
        if self.input_cfg.debug_inputs:
            self.log.debug(f"[CENTER DEBUG] out.extra = {out.extra}")

        ttype = out.extra.get("target_type", "Virtual")
        tval  = out.extra.get("target_val")
        pos   = out.extra.get("position")

        fx, fy = None, None
        px, py = None, None

        if pos:
            if pos[0] == "frac":
                fx, fy = pos[1]
            elif pos[0] == "px":
                px, py = pos[1]

        if fx is None and px is None:
            fx, fy = 0.5, 0.5

        if ttype == "Virtual":
            if px is not None:
                self.mousecontroller.set_position_pixels(px, py)
            else:
                self.mousecontroller.set_position_frac(fx, fy)

        elif ttype == "Monitor":
            idx = int(tval) if tval and str(tval).isdigit() else 0
            if px is not None:
                self.mousecontroller.set_position_monitor_px(idx, px, py)
            else:
                self.mousecontroller.set_position_monitor_frac(idx, fx, fy)

        elif ttype == "WindowClass":
            if px is not None:
                self.mousecontroller.set_position_window_px(class_name=tval, x=px, y=py)
            else:
                self.mousecontroller.set_position_window_frac(class_name=tval, fx=fx, fy=fy)

        elif ttype == "WindowName":
            if px is not None:
                self.mousecontroller.set_position_window_px(title=tval, x=px, y=py)
            else:
                self.mousecontroller.set_position_window_frac(title=tval, fx=fx, fy=fy)

    # ---------------------------------------------------------------
    # FocusWindow
    # ---------------------------------------------------------------
    def _exec_focus(self, out):
        ttype = out.extra.get("target_type", "WindowName")
        tval  = out.extra.get("target_val")
        hwnd = None
        if ttype == "WindowClass":
            hwnd = self.mousecontroller.find_window(class_name=tval)
        else:
            hwnd = self.mousecontroller.find_window(title=tval)

        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            if not user32.SetForegroundWindow(hwnd):
                user32.keybd_event(0x12, 0, 0, 0)   # ALT down
                user32.keybd_event(0x12, 0, 2, 0)   # ALT up
                user32.SetForegroundWindow(hwnd)

    # ---------------------------------------------------------------
    # Wiggle
    # ---------------------------------------------------------------
    def _toggle_wiggle(self, out):
        self.wiggle_active = not self.wiggle_active
        if out.extra:
            self.wiggle_mode = out.extra.get("wiggle_mode", "relative")
            self.wiggle_px = out.extra.get("wiggle_px", 5)
            self.wiggle_ms = out.extra.get("wiggle_ms", 1000)
        if self.input_cfg.debug_inputs:
            self.log.info(f"[WIGGLE] {'ON' if self.wiggle_active else 'OFF'}")


    def _update_wiggle(self):
        if not self.wiggle_active:
            return
        now = time.time() * 1000.0
        if now - self.last_wiggle >= self.wiggle_ms:
            dx = self.wiggle_px if int(now/self.wiggle_ms) % 2 == 0 else -self.wiggle_px
            if self.wiggle_mode == "relative":
                self.mousecontroller.move_relative(dx, 0)
            else:
                pt = wt.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                self.mousecontroller.set_position_pixels(pt.x + dx, pt.y)
            self.last_wiggle = now

    # ---------------------------------------------------------------
    # MouseInc / MouseDec
    # ---------------------------------------------------------------
    def _inc_key(self, ib, out):
        return (ib.device_index, ib.device_guid, ib.input_id, out.value)

    def _start_increment(self, ib, out):
        now = time.time()
        self.increment_state[self._inc_key(ib, out)] = {
            "start": now, "last": now, "out": out
        }

    def _stop_increment(self, ib, out):
        key = self._inc_key(ib, out)
        if key in self.increment_state:
            del self.increment_state[key]

    def _update_increments(self):
        if not self.increment_state:
            return
        now = time.time()
        for key, state in list(self.increment_state.items()):
            out = state["out"]
            init = max(1, int(out.wheel_init or 5))
            vmax = max(init, int(out.wheel_max or 30))
            ramp_ms = max(1, int(out.wheel_accel or 1000))

            start = state["start"]
            last = state["last"]

            elapsed_ms = (now - start) * 1000.0
            if elapsed_ms >= ramp_ms:
                rate = float(vmax)
            else:
                rate = init + (vmax - init) * (elapsed_ms / ramp_ms)

            interval = 1.0 / max(1e-6, rate)
            while now - last >= interval:
                axis = out.extra.get("axis", "x")
                amount = out.extra.get("amount", 1)
                mode = out.extra.get("mode", "relative")
                if mode == "relative":
                    if axis == "x":
                        self.mousecontroller.move_relative(amount, 0)
                    else:
                        self.mousecontroller.move_relative(0, amount)
                else:
                    pt = wt.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    if axis == "x":
                        self.mousecontroller.set_position_pixels(pt.x + amount, pt.y)
                    else:
                        self.mousecontroller.set_position_pixels(pt.x, pt.y + amount)
                last += interval
            state["last"] = last
