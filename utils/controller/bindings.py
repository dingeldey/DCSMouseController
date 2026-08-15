from dataclasses import dataclass
from typing import Optional, Literal
import re

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
    # Holds either:
    # - a GUID string
    # - or a device name string
    # Numeric device references still go into device_index.
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

    dev_id = parts[1].strip()
    guid = None
    device_index = None

    # Numeric = joystick index
    # Otherwise store the raw string, which may be either:
    # - a GUID
    # - or a device name
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
        # Allow three forms:
        #   A) legacy:  dev:...:axis:<id>:pos|neg|abs:<thr>
        #   B) inline:  dev:...:axis:<id><op><value>        (e.g. axis:1>0.6, axis:1<-0.6)
        #   C) tokens:  dev:...:axis:<id>:<op>:<value>      (e.g. axis:1:>:0.6, axis:1:<:-0.6)
        axis_tok = parts[offset + 1]

        # --- Form B: inline comparator in the axis token (e.g. "1>0.6" or "1 < -0.6")
        m = re.match(r"^\s*(\d+)\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$", axis_tok)
        if m:
            axis_id = int(m.group(1))
            op = m.group(2)
            val = float(m.group(3))
            if op in (">", ">="):
                return InputBinding(guid, device_index, "axis", axis_id,
                                    axis_mode="pos", threshold=val,
                                    modifier_layer=modifier_layer)
            elif op in ("<", "<="):
                if val >= 0:
                    raise ValueError(
                        f"Use a negative value for '<' comparator (e.g. axis:{axis_id} < -0.6); got {val}"
                    )
                return InputBinding(guid, device_index, "axis", axis_id,
                                    axis_mode="neg", threshold=abs(val),
                                    modifier_layer=modifier_layer)

        # parse plain axis id
        axis_id = int(axis_tok)

        mode = None
        thr = None

        # --- Form C: colon-separated comparator tokens (e.g. ":>:0.6" or ":<:-0.6")
        if len(parts) > offset + 2 and parts[offset + 2] in (">", ">=", "<", "<="):
            op = parts[offset + 2]
            val = float(parts[offset + 3])
            if op in (">", ">="):
                return InputBinding(guid, device_index, "axis", axis_id,
                                    axis_mode="pos", threshold=val,
                                    modifier_layer=modifier_layer)
            else:  # < or <=
                if val >= 0:
                    raise ValueError(
                        f"Use a negative value for '<' comparator (e.g. axis:{axis_id}:<:-0.6); got {val}"
                    )
                return InputBinding(guid, device_index, "axis", axis_id,
                                    axis_mode="neg", threshold=abs(val),
                                    modifier_layer=modifier_layer)

        # --- Form A: legacy pos/neg/abs remains supported
        if len(parts) > offset + 2:
            mode = parts[offset + 2]
            if mode in ("pos", "neg", "abs"):
                thr = float(parts[offset + 3])

        return InputBinding(guid, device_index, "axis", axis_id,
                            axis_mode=mode, threshold=thr,
                            modifier_layer=modifier_layer)

    raise ValueError(f"Unsupported input type in {binding_str}")

# ---------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------
def parse_output(action_str: str) -> OutputAction:
    # The GUI and runtime intentionally share one parser so the labeled fields
    # always serialize to exactly what execution expects.
    from utils.output_actions import parse_action

    spec = parse_action(action_str)
    values = spec.values
    if spec.kind == "Keyboard key":
        return OutputAction("key", values["shortcut"], values.get("mode", "single"),
                            extra={"hold_ms": int(values.get("duration", 30))})
    if spec.kind == "Mouse button":
        return OutputAction("mouse_button", values["button"], values.get("mode", "single"),
                            extra={"hold_ms": int(values.get("duration", 30))})
    if spec.kind == "Mouse wheel":
        return OutputAction("mouse_wheel", values["direction"], values.get("mode", "single"),
                            int(values.get("initial", 5)), int(values.get("maximum", 30)),
                            int(values.get("ramp", 1000)))
    if spec.kind == "Mouse movement axis":
        return OutputAction("mouse_axis", values["axis"], "single")
    if spec.kind == "Center mouse":
        coordinate_mode = values.get("coordinate_mode", "frac")
        caster = int if coordinate_mode == "px" else float
        position = (coordinate_mode, (caster(float(values.get("x", 0.5))), caster(float(values.get("y", 0.5)))))
        extra = {"target_type": values.get("target_type", "Virtual"),
                 "target_val": values.get("target") or None, "position": position}
        return OutputAction("mouse_center", "CenterMouse", "single", extra=extra)
    if spec.kind == "Focus window":
        extra = {"target_type": values.get("target_type", "WindowName"),
                 "target_val": values.get("target") or None}
        return OutputAction("focus_window", "FocusWindow", "single", extra=extra)
    if spec.kind == "Wiggle mouse":
        extra = {"wiggle_mode": values.get("mode", "relative"),
                 "wiggle_px": int(values.get("pixels", 5)), "wiggle_ms": int(values.get("period", 1000))}
        return OutputAction("mouse_wiggle", "WiggleMouse", "toggle", extra=extra)
    if spec.kind == "Mouse increment":
        amount = 1 if values.get("direction", "Increase") == "Increase" else -1
        extra = {"axis": values.get("axis", "x"), "amount": amount,
                 "mode": values.get("mode", "relative")}
        name = "MouseInc" if amount > 0 else "MouseDec"
        return OutputAction("mouse_increment", name, "hold", int(values.get("initial", 5)),
                            int(values.get("maximum", 30)), int(values.get("ramp", 1000)), extra=extra)

    # Preserve the old fallback: an unrecognized raw token is attempted as a key.
    return OutputAction("key", action_str.split(":", 1)[0], "single", extra={"hold_ms": 30})

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
        # Wiggle
        self.wiggle_initially_on = False
        self.wiggle_px = 5
        self.wiggle_ms = 1000

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

        # --- wiggle_initially_on with params ---
        if cfg.cfg.has_option("input", "wiggle_initially_on"):
            raw = cfg.get_str("input", "wiggle_initially_on")
            tokens = [t.strip() for t in raw.split(":")]

            # first token = boolean
            if tokens[0].lower() in ("1", "true", "yes", "on"):
                obj.wiggle_initially_on = True
            else:
                obj.wiggle_initially_on = False

            # optional amplitude
            if len(tokens) > 1 and tokens[1].isdigit():
                obj.wiggle_px = int(tokens[1])

            # optional period
            if len(tokens) > 2 and tokens[2].isdigit():
                obj.wiggle_ms = int(tokens[2])

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
                    + ", ".join(f"{o.type}:{o.value}:{o.mode}, extra={o.extra}" for o in bm.outputs)
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
                    + ", ".join(f"{o.type}:{o.value}:{o.mode}, extra={o.extra}" for o in bm.outputs)
                )
        return maps
