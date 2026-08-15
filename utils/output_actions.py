"""Parse and render the user-facing output action syntax."""

from __future__ import annotations

from dataclasses import dataclass, field
import re


ACTION_TYPES = (
    "Keyboard key",
    "Mouse button",
    "Mouse wheel",
    "Mouse movement axis",
    "Center mouse",
    "Focus window",
    "Wiggle mouse",
    "Mouse increment",
    "Advanced / raw",
)


def split_action(value: str) -> list[str]:
    parts, buffer, bracketed = [], "", False
    for character in value:
        if character == "[":
            bracketed = True
        elif character == "]":
            bracketed = False
        if character == ":" and not bracketed:
            parts.append(buffer.strip())
            buffer = ""
        else:
            buffer += character
    parts.append(buffer.strip())
    return parts


@dataclass
class ActionSpec:
    kind: str = "Keyboard key"
    values: dict[str, str] = field(default_factory=dict)
    original: str = ""


def _mode_and_numbers(tokens: list[str]) -> tuple[str, list[str]]:
    mode = next((token.lower() for token in tokens if token.lower() in {"single", "hold", "toggle"}), "single")
    return mode, [token for token in tokens if token.lower() not in {"single", "hold", "toggle"}]


def parse_action(raw: str) -> ActionSpec:
    parts = split_action(raw.strip())
    base = parts[0] if parts else ""
    rest = parts[1:]
    mode, parameters = _mode_and_numbers(rest)

    if re.fullmatch(r"MB[1-5]", base, re.I):
        return ActionSpec("Mouse button", {
            "button": base.upper(), "mode": mode,
            "duration": next((value for value in reversed(parameters) if value.isdigit()), "30"),
        }, raw)
    if base in {"WheelUp", "WheelDown"}:
        numbers = [value for value in parameters if re.fullmatch(r"\d+", value)]
        numbers += ["5", "30", "1000"]
        return ActionSpec("Mouse wheel", {
            "direction": base, "mode": mode, "initial": numbers[0], "maximum": numbers[1], "ramp": numbers[2],
        }, raw)
    if base.lower() in {"mouse_x", "mouse_y"}:
        return ActionSpec("Mouse movement axis", {"axis": base[-1].lower()}, raw)
    if base == "CenterMouse":
        target_type = parts[1] if len(parts) > 1 and parts[1] else "Virtual"
        coordinate_index = next((i for i, value in enumerate(parts) if value in {"frac", "px"}), -1)
        target = ":".join(parts[2:coordinate_index]) if coordinate_index > 2 else (parts[2] if len(parts) > 2 and coordinate_index < 0 else "")
        coordinate_mode = parts[coordinate_index] if coordinate_index >= 0 else "frac"
        coordinate = parts[coordinate_index + 1] if coordinate_index + 1 < len(parts) else "[0.5,0.5]"
        match = re.fullmatch(r"\[\s*([^,]+)\s*,\s*([^]]+)\s*\]", coordinate)
        x, y = match.groups() if match else ("0.5", "0.5")
        return ActionSpec("Center mouse", {
            "target_type": target_type, "target": target, "coordinate_mode": coordinate_mode, "x": x, "y": y,
        }, raw)
    if base == "FocusWindow":
        return ActionSpec("Focus window", {
            "target_type": parts[1] if len(parts) > 1 else "WindowName",
            "target": ":".join(parts[2:]) if len(parts) > 2 else "",
        }, raw)
    if base == "WiggleMouse":
        return ActionSpec("Wiggle mouse", {
            "mode": parts[1] if len(parts) > 1 else "relative",
            "pixels": parts[2] if len(parts) > 2 else "5",
            "period": parts[3] if len(parts) > 3 else "1000",
        }, raw)
    if base in {"MouseInc", "MouseDec"}:
        return ActionSpec("Mouse increment", {
            "direction": "Increase" if base == "MouseInc" else "Decrease",
            "axis": parts[1] if len(parts) > 1 else "x",
            "mode": parts[2] if len(parts) > 2 else "relative",
            "initial": parts[4] if len(parts) > 4 else "5",
            "maximum": parts[5] if len(parts) > 5 else "30",
            "ramp": parts[6] if len(parts) > 6 else "1000",
        }, raw)

    # Keys are deliberately the fallback because any supported key combination
    # has no identifying prefix.
    if base and re.fullmatch(r"[A-Za-z0-9+]+", base):
        duration = next((value for value in reversed(parameters) if value.isdigit()), "30")
        return ActionSpec("Keyboard key", {"shortcut": base, "mode": mode, "duration": duration}, raw)
    return ActionSpec("Advanced / raw", {"raw": raw}, raw)


def render_action(spec: ActionSpec) -> str:
    values = spec.values
    if spec.kind == "Keyboard key":
        result = values.get("shortcut", "").strip()
        mode = values.get("mode", "single")
        if mode == "single":
            duration = values.get("duration", "30").strip()
            return f"{result}:single:{duration}" if duration and duration != "30" else result
        return f"{result}:{mode}"
    if spec.kind == "Mouse button":
        result = values.get("button", "MB1")
        mode = values.get("mode", "single")
        if mode == "single":
            duration = values.get("duration", "30").strip()
            return f"{result}:single:{duration}" if duration and duration != "30" else result
        return f"{result}:{mode}"
    if spec.kind == "Mouse wheel":
        direction = values.get("direction", "WheelUp")
        if values.get("mode", "single") == "single":
            return direction
        return f"{direction}:hold:{values.get('initial', '5')}:{values.get('maximum', '30')}:{values.get('ramp', '1000')}"
    if spec.kind == "Mouse movement axis":
        return f"mouse_{values.get('axis', 'x')}"
    if spec.kind == "Center mouse":
        target_type = values.get("target_type", "Virtual")
        target = values.get("target", "").strip()
        target_token = f":{target}" if target else ""
        return (f"CenterMouse:{target_type}{target_token}:{values.get('coordinate_mode', 'frac')}:"
                f"[{values.get('x', '0.5')},{values.get('y', '0.5')}]")
    if spec.kind == "Focus window":
        return f"FocusWindow:{values.get('target_type', 'WindowName')}:{values.get('target', '').strip()}"
    if spec.kind == "Wiggle mouse":
        return f"WiggleMouse:{values.get('mode', 'relative')}:{values.get('pixels', '5')}:{values.get('period', '1000')}"
    if spec.kind == "Mouse increment":
        name = "MouseInc" if values.get("direction", "Increase") == "Increase" else "MouseDec"
        return (f"{name}:{values.get('axis', 'x')}:{values.get('mode', 'relative')}:hold:"
                f"{values.get('initial', '5')}:{values.get('maximum', '30')}:{values.get('ramp', '1000')}")
    return values.get("raw", spec.original).strip()


def describe_action(raw: str) -> str:
    spec = parse_action(raw)
    v = spec.values
    if spec.kind == "Keyboard key":
        mode = {"single": "press", "hold": "while held", "toggle": "toggle"}.get(v.get("mode"), v.get("mode"))
        return f"Keyboard · {v.get('shortcut')} · {mode}"
    if spec.kind == "Mouse button":
        return f"Mouse · {v.get('button')} · {v.get('mode')}"
    if spec.kind == "Mouse wheel":
        detail = "one tick" if v.get("mode") == "single" else f"hold {v.get('initial')}→{v.get('maximum')} ticks/s"
        return f"Wheel · {'up' if v.get('direction') == 'WheelUp' else 'down'} · {detail}"
    if spec.kind == "Mouse movement axis":
        return f"Mouse movement · {v.get('axis', 'x').upper()} axis"
    if spec.kind == "Center mouse":
        target_type, target_value = v.get("target_type"), v.get("target")
        target = f"{target_type} {target_value}" if target_value else target_type
        return f"Center mouse · {target} · {v.get('x')}, {v.get('y')} {v.get('coordinate_mode')}"
    if spec.kind == "Focus window":
        return f"Focus window · {v.get('target') or '(target not set)'}"
    if spec.kind == "Wiggle mouse":
        return f"Wiggle mouse · {v.get('pixels')} px every {v.get('period')} ms"
    if spec.kind == "Mouse increment":
        return f"Mouse {v.get('direction', '').lower()} · {v.get('axis', 'x').upper()} axis"
    return f"Advanced · {raw}"
