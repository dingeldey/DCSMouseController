"""Controller enumeration and input listening helpers used by the GUI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControllerDevice:
    index: int
    name: str
    guid: str
    buttons: int
    axes: int

    @property
    def label(self) -> str:
        return f"{self.name}  ·  {self.buttons} buttons / {self.axes} axes  ·  {self.guid}"


class ControllerService:
    def __init__(self) -> None:
        self.pygame = None
        self.joysticks = []

    def refresh(self) -> list[ControllerDevice]:
        try:
            import pygame
        except ImportError as exc:
            raise RuntimeError("pygame is not installed. Run: pip install pygame") from exc

        self.pygame = pygame
        pygame.init()
        pygame.joystick.init()
        self.joysticks = []
        devices = []
        for index in range(pygame.joystick.get_count()):
            joystick = pygame.joystick.Joystick(index)
            joystick.init()
            guid = joystick.get_guid() if hasattr(joystick, "get_guid") else f"index-{index}"
            self.joysticks.append(joystick)
            devices.append(
                ControllerDevice(index, joystick.get_name(), guid, joystick.get_numbuttons(), joystick.get_numaxes())
            )
        return devices

    def snapshot(self, index: int) -> tuple[list[int], list[float]]:
        if self.pygame is None:
            raise RuntimeError("Controllers have not been refreshed")
        self.pygame.event.pump()
        joystick = self.joysticks[index]
        return (
            [joystick.get_button(i) for i in range(joystick.get_numbuttons())],
            [joystick.get_axis(i) for i in range(joystick.get_numaxes())],
        )

    def detect_change(
        self, index: int, baseline: tuple[list[int], list[float]], axis_delta: float = 0.55
    ) -> tuple[str, int, str | None] | None:
        buttons, axes = self.snapshot(index)
        old_buttons, old_axes = baseline
        for button, state in enumerate(buttons):
            if state and (button >= len(old_buttons) or not old_buttons[button]):
                return "button", button + 1, None
        for axis, value in enumerate(axes):
            old = old_axes[axis] if axis < len(old_axes) else 0.0
            if abs(value - old) >= axis_delta:
                mode = "pos" if value > old else "neg"
                return "axis", axis, mode
        return None
