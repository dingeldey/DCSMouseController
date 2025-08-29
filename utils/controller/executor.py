#!/usr/bin/env python3
"""
executor.py - Executes actions for input events. Supports:
- key presses
- mouse button clicks
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
        self.wiggle_active = False
        self.last_wiggle = 0
        self.wiggle_px = 5
        self.wiggle_ms = 1000
        self.wiggle_mode = "relative"

        # increment state (per-binding)
        self.increment_state = {}

    # ---------------------------------------------------------------
    # Event handling
    # ---------------------------------------------------------------
    def handle_event(self, event):
        ib = event.binding.input
        for out in event.binding.outputs:
            if out.type == "key" and event.pressed:
                self._exec_key(out)

            elif out.type == "mouse_button" and event.pressed:
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

    # ---------------------------------------------------------------
    # Keys / Buttons
    # ---------------------------------------------------------------
    def _exec_key(self, out):
        if self.input_cfg.debug_inputs:
            self.log.info(f"[INPUT] key {out.value}")
        self.keymapper.send_key(out.value)

    def _exec_button(self, out, event):
        if event.pressed:
            if self.input_cfg.debug_inputs:
                self.log.info(f"[INPUT] mouse button {out.value}")
            self.mousecontroller.click(out.value)

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

        if self.input_cfg.debug_inputs:
            self.log.info(
                f"[INPUT] axis {axis_name.upper()} val={value:.3f} vel={velocity:.1f} step={step}"
            )

    # ---------------------------------------------------------------
    # CenterMouse
    # ---------------------------------------------------------------
    def _exec_center(self, out):
        if self.input_cfg.debug_inputs:
            self.log.info(f"[CENTER DEBUG] out.extra = {out.extra}")

        ttype = out.extra.get("target_type", "Virtual")
        tval  = out.extra.get("target_val")
        pos   = out.extra.get("position")

        # Default: center
        fx, fy = None, None
        px, py = None, None

        if pos:
            if pos[0] == "frac":
                fx, fy = pos[1]  # tuple (x,y)
            elif pos[0] == "px":
                px, py = pos[1]  # tuple (x,y)

        # fallback only if nothing was parsed
        if fx is None and px is None:
            fx, fy = 0.5, 0.5

        if ttype == "Virtual":
            if px is not None:
                self.mousecontroller.set_position_pixels(px, py)
            else:
                self.mousecontroller.set_position_frac(fx, fy)
            if self.input_cfg.debug_inputs:
                self.log.info(f"[CENTER] Virtual ({'px' if px else 'frac'}) {px or fx}, {py or fy}")

        elif ttype == "Monitor":
            idx = int(tval) if tval and str(tval).isdigit() else 0
            if px is not None:
                self.mousecontroller.set_position_monitor_px(idx, px, py)
            else:
                self.mousecontroller.set_position_monitor_frac(idx, fx, fy)
            if self.input_cfg.debug_inputs:
                self.log.info(f"[CENTER] Monitor {idx} ({'px' if px else 'frac'}) {px or fx}, {py or fy}")

        elif ttype == "WindowClass":
            if px is not None:
                self.mousecontroller.set_position_window_px(class_name=tval, x=px, y=py)
            else:
                self.mousecontroller.set_position_window_frac(class_name=tval, fx=fx, fy=fy)
            if self.input_cfg.debug_inputs:
                self.log.info(f"[CENTER] WindowClass {tval} ({'px' if px else 'frac'}) {px or fx}, {py or fy}")

        elif ttype == "WindowName":
            if px is not None:
                self.mousecontroller.set_position_window_px(title=tval, x=px, y=py)
            else:
                self.mousecontroller.set_position_window_frac(title=tval, fx=fx, fy=fy)
            if self.input_cfg.debug_inputs:
                self.log.info(f"[CENTER] WindowName {tval} ({'px' if px else 'frac'}) {px or fx}, {py or fy}")


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
            if self.input_cfg.debug_inputs:
                self.log.info(f"[FOCUS] Brought window {tval} to foreground")

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
            if self.input_cfg.debug_inputs:
                self.log.info(f"[WIGGLE] step {dx}")

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
        if self.input_cfg.debug_inputs:
            self.log.info(f"[INC] {out.value} START")

    def _stop_increment(self, ib, out):
        key = self._inc_key(ib, out)
        if key in self.increment_state:
            if self.input_cfg.debug_inputs:
                self.log.info(f"[INC] {out.value} STOP")
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
                if self.input_cfg.debug_inputs:
                    self.log.info(f"[INC] {out.value} TICK axis={axis} amt={amount} rate={rate:.1f}/s")
            state["last"] = last
