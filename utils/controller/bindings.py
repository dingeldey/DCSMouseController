from dataclasses import dataclass
from typing import Optional, Literal

# ---------------------------------------------------------------
# Helper: split binding string but keep [x,y] coordinates together
# ---------------------------------------------------------------
def split_binding_string(s: str) -> list[str]:
    parts = []
    buf = ""
    in_brackets = False
    for ch in s:
        if ch == "[":
            in_brackets = True
            buf += ch
        elif ch == "]":
            in_brackets = False
            buf += ch
        elif ch == ":" and not in_brackets:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]

# ---------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------
@dataclass
class InputBinding:
    device_guid: Optional[str]
    device_index: Optional[int] = None
    input_type: Literal["button","axis"] = "button"
    input_id: int = 0
    axis_mode: Optional[Literal["pos","neg","abs"]] = None
    threshold: Optional[float] = None
    modifier_layer: bool = False

@dataclass
class OutputAction:
    type: Literal[
        "key","mouse_button","mouse_wheel","mouse_axis",
        "mouse_center","mouse_wiggle","focus_window","mouse_increment"
    ]
    value: str
    mode: Literal["single","hold","toggle"] = "single"
    wheel_init: int = 0
    wheel_max: int = 0
    wheel_accel: int = 0
    extra: Optional[dict] = None

@dataclass
class BindingMap:
    input: InputBinding
    outputs: list[OutputAction]

# ---------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------
def parse_input(binding_str: str) -> InputBinding:
    parts = binding_str.split(":")
    modifier_layer = False
    if parts[-1] in ("M", ":M"):
        modifier_layer = True
        parts = parts[:-1]

    if parts[0] != "dev":
        raise ValueError(f"Binding must start with 'dev:' ({binding_str})")

    dev_id = parts[1]
    guid = None
    device_index = None
    if dev_id.isdigit():
        device_index = int(dev_id)
    else:
        guid = dev_id

    offset = 2
    if parts[offset] == "button":
        btn_number = int(parts[offset + 1])
        if btn_number <= 0:
            raise ValueError(
                f"Invalid button binding '{binding_str}': "
                f"button numbers in INI are 1-based (got {btn_number})."
            )
        return InputBinding(guid, device_index, "button",
                            btn_number - 1,
                            modifier_layer=modifier_layer)
    elif parts[offset] == "axis":
        axis_id = int(parts[offset + 1])
        mode = None
        thr = None
        if len(parts) > offset+2:
            mode = parts[offset+2]
            if mode in ("pos","neg","abs"):
                thr = float(parts[offset+3])
        return InputBinding(guid, device_index, "axis", axis_id,
                            axis_mode=mode, threshold=thr,
                            modifier_layer=modifier_layer)
    raise ValueError(f"Unsupported input type in {binding_str}")

# ---------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------
def parse_output(action_str: str) -> OutputAction:
    parts = split_binding_string(action_str)
    base = parts[0]

    # detect :single / :hold / :toggle at the end
    mode = "single"
    if parts[-1] in ("single","hold","toggle"):
        mode = parts[-1]
        parts = parts[:-1]

    # --- Mouse buttons ---
    if base.startswith("MB"):
        hold_ms = 30
        # Optional last numeric → hold_ms
        if parts and parts[-1].isdigit():
            hold_ms = int(parts[-1])
            parts = parts[:-1]
        return OutputAction("mouse_button", base, mode, extra={"hold_ms": hold_ms})

    # --- Mouse wheel ---
    if base.startswith("Wheel"):
        wheel_init = wheel_max = wheel_accel = 0
        if mode == "hold" and len(parts) >= 4:
            wheel_init = int(parts[1]); wheel_max = int(parts[2]); wheel_accel = int(parts[3])
        return OutputAction("mouse_wheel", base, mode,
                            wheel_init, wheel_max, wheel_accel)

    # --- Mouse axes ---
    if base.lower().startswith("mouse_"):
        return OutputAction("mouse_axis", base.split("_")[1].lower(), mode)

    # --- CenterMouse ---
    if base == "CenterMouse":
        target_type = "Virtual"
        target_val  = None
        pos = None

        for token in parts[1:]:
            if token in ("Virtual","Monitor","WindowClass","WindowName"):
                target_type = token
            elif token.startswith("[") and token.endswith("]"):
                try:
                    x_str, y_str = token[1:-1].split(",")
                    fx, fy = float(x_str), float(y_str)
                    if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
                        pos = ("frac", (fx, fy))
                    else:
                        pos = ("px", (int(float(x_str)), int(float(y_str))))
                except Exception:
                    pos = None
            else:
                target_val = token

        extra = {"target_type": target_type, "target_val": target_val, "position": pos}
        return OutputAction("mouse_center", base, "single", extra=extra)

    # --- WiggleMouse ---
    if base == "WiggleMouse":
        wiggle_mode = parts[1] if len(parts) > 1 else "relative"
        wiggle_px   = int(parts[2]) if len(parts) > 2 else 5
        wiggle_ms   = int(parts[3]) if len(parts) > 3 else 1000
        extra = {"wiggle_mode": wiggle_mode, "wiggle_px": wiggle_px, "wiggle_ms": wiggle_ms}
        return OutputAction("mouse_wiggle", base, "toggle", extra=extra)

    # --- FocusWindow ---
    if base == "FocusWindow":
        target_type = parts[1] if len(parts) > 1 else "WindowName"
        target_val  = parts[2] if len(parts) > 2 else None
        extra = {"target_type": target_type, "target_val": target_val}
        return OutputAction("focus_window", base, "single", extra=extra)

    # --- MouseInc / MouseDec ---
    if base in ("MouseInc","MouseDec"):
        axis = parts[1] if len(parts) > 1 else "x"
        inc_mode = parts[2] if len(parts) > 2 else "relative"
        if len(parts) < 7 or parts[3] != "hold":
            raise ValueError(f"MouseInc/Dec requires syntax MouseInc:x:relative:hold:init:max:ms (got {action_str})")
        init = int(parts[4]); vmax = int(parts[5]); ramp = int(parts[6])
        amount = 1 if base == "MouseInc" else -1
        extra = {"axis": axis, "amount": amount, "mode": inc_mode}
        return OutputAction("mouse_increment", base, "hold", init, vmax, ramp, extra=extra)

    # --- Default: Key ---
    return OutputAction("key", base, mode)


# ---------------------------------------------------------------
# Config classes
# ---------------------------------------------------------------
class InputConfig:
    def __init__(self, modifier=None, toggle=None):
        self.modifier = modifier
        self.toggle = toggle
        self.axis_deadzone = 0.05
        self.axis_speed = 400
        self.axis_mode = "relative"
        self.axis_poll_hz = 250
        # Debug
        self.debug_inputs = False
        self.log_buttons = False
        self.log_axes = False

    @classmethod
    def from_ini(cls, cfg):
        mod = None
        tog = None
        if cfg.cfg.has_option("input", "modifier"):
            val = cfg.get_str("input", "modifier")
            if val:
                mod = parse_input(val)
        if cfg.cfg.has_option("input", "button_toggle"):
            val = cfg.get_str("input", "button_toggle")
            if val:
                tog = parse_input(val)
        obj = cls(mod, tog)

        if cfg.cfg.has_option("input", "axis_deadzone"):
            obj.axis_deadzone = float(cfg.get_str("input", "axis_deadzone"))
        if cfg.cfg.has_option("input", "axis_speed"):
            obj.axis_speed = float(cfg.get_str("input", "axis_speed"))
        if cfg.cfg.has_option("input", "axis_mode"):
            obj.axis_mode = cfg.get_str("input", "axis_mode")
        if cfg.cfg.has_option("input", "axis_poll_hz"):
            obj.axis_poll_hz = int(cfg.get_str("input", "axis_poll_hz"))

        if cfg.cfg.has_option("input", "debug_inputs"):
            obj.debug_inputs = cfg.cfg.getboolean("input", "debug_inputs")
        if cfg.cfg.has_option("input", "log_buttons"):
            obj.log_buttons = cfg.cfg.getboolean("input", "log_buttons")
        if cfg.cfg.has_option("input", "log_axes"):
            obj.log_axes = cfg.cfg.getboolean("input", "log_axes")
        return obj


class KeyMapConfig:
    @classmethod
    def from_ini(cls, cfg, log=None):
        maps: list[BindingMap] = []
        if cfg.cfg.has_option("input", "key_mappings"):
            lines = cfg.get_list("input", "key_mappings")
            for line in lines:
                for entry in line.split("\\"):
                    if "=>" not in entry:
                        continue
                    lhs, rhs = [x.strip() for x in entry.split("=>", 1)]
                    inp = parse_input(lhs)
                    out = parse_output(rhs)

                    existing = next((bm for bm in maps if bm.input == inp), None)
                    if existing:
                        existing.outputs.append(out)
                    else:
                        maps.append(BindingMap(inp, [out]))

        if log:
            log.info(f"[BINDINGS] Loaded {len(maps)} key mappings")
            for bm in maps:
                log.info(
                    f"[BINDING] Input={bm.input} → "
                    + ", ".join(f"{o.type}:{o.value}:{o.mode}" for o in bm.outputs)
                )
        return maps


class AxisMapConfig:
    @classmethod
    def from_ini(cls, cfg, log=None):
        maps: list[BindingMap] = []
        if cfg.cfg.has_option("input", "axis_mappings"):
            lines = cfg.get_list("input", "axis_mappings")
            for line in lines:
                for entry in line.split("\\"):
                    if "=>" not in entry:
                        continue
                    lhs, rhs = [x.strip() for x in entry.split("=>", 1)]
                    inp = parse_input(lhs)
                    out = parse_output(rhs)

                    existing = next((bm for bm in maps if bm.input == inp), None)
                    if existing:
                        existing.outputs.append(out)
                    else:
                        maps.append(BindingMap(inp, [out]))

        if log:
            log.info(f"[BINDINGS] Loaded {len(maps)} axis mappings")
            for bm in maps:
                log.info(
                    f"[BINDING] Input={bm.input} → "
                    + ", ".join(f"{o.type}:{o.value}:{o.mode}" for o in bm.outputs)
                )
        return maps

