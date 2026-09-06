import unittest

from utils.controller.bindings import parse_output
from utils.output_actions import ActionSpec, describe_action, parse_action, render_action


class OutputActionTests(unittest.TestCase):
    def test_documented_wheel_hold_syntax(self):
        spec = parse_action("WheelDown:hold:1:35:250")
        self.assertEqual("Mouse wheel", spec.kind)
        self.assertEqual({"direction": "WheelDown", "mode": "hold", "initial": "1", "maximum": "35", "ramp": "250"}, spec.values)
        runtime = parse_output("WheelDown:hold:1:35:250")
        self.assertEqual("hold", runtime.mode)
        self.assertEqual((1, 35, 250), (runtime.wheel_init, runtime.wheel_max, runtime.wheel_accel))

    def test_key_mode_and_duration(self):
        runtime = parse_output("Ctrl+Shift+F5:single:80")
        self.assertEqual("key", runtime.type)
        self.assertEqual("single", runtime.mode)
        self.assertEqual(80, runtime.extra["hold_ms"])

    def test_center_mouse_round_trip(self):
        raw = "CenterMouse:Monitor:1:px:[200,250]"
        spec = parse_action(raw)
        self.assertEqual(raw, render_action(spec))
        self.assertEqual("Monitor", spec.values["target_type"])
        self.assertEqual(("200", "250"), (spec.values["x"], spec.values["y"]))

    def test_all_structured_types_render(self):
        cases = (
            ActionSpec("Mouse button", {"button": "MB2", "mode": "toggle", "duration": "30"}),
            ActionSpec("Mouse movement axis", {"axis": "y"}),
            ActionSpec("Focus window", {"target_type": "WindowClass", "target": "DCS"}),
            ActionSpec("Wiggle mouse", {"mode": "relative", "pixels": "2", "period": "500"}),
            ActionSpec("Mouse increment", {"direction": "Decrease", "axis": "x", "mode": "absolute", "initial": "5", "maximum": "20", "ramp": "750"}),
        )
        for case in cases:
            with self.subTest(kind=case.kind):
                rendered = render_action(case)
                self.assertEqual(case.kind, parse_action(rendered).kind)

    def test_summary_explains_raw_syntax(self):
        self.assertEqual("Wheel · up · hold 5→30 ticks/s", describe_action("WheelUp:hold:5:30:1000"))

    def test_focus_window_target_with_colon_round_trips(self):
        spec = ActionSpec("Focus window", {"target_type": "WindowName", "target": "DCS: World"})
        rendered = render_action(spec)
        self.assertEqual("FocusWindow:WindowName:[DCS: World]", rendered)
        self.assertEqual("DCS: World", parse_action(rendered).values["target"])

    def test_center_mouse_target_with_colon_round_trips(self):
        spec = ActionSpec("Center mouse", {
            "target_type": "WindowName", "target": "DCS: World",
            "coordinate_mode": "frac", "x": "0.5", "y": "0.5",
        })
        rendered = render_action(spec)
        self.assertIn("[DCS: World]", rendered)
        self.assertEqual("DCS: World", parse_action(rendered).values["target"])

    def test_target_without_colon_stays_unbracketed(self):
        spec = ActionSpec("Focus window", {"target_type": "WindowClass", "target": "DCS"})
        rendered = render_action(spec)
        self.assertEqual("FocusWindow:WindowClass:DCS", rendered)


if __name__ == "__main__":
    unittest.main()
