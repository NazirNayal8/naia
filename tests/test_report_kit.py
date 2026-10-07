"""Report-kit contracts using Node built-ins and a small DOM fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is needed for report-kit JavaScript contracts")
class ReportKitTest(unittest.TestCase):
    def case(self, name):
        result = subprocess.run([NODE, str(ROOT / "tests/report_kit_dom_fixture.cjs"),
            str(ROOT / "src/naia/assets/report_kit.js"), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_value(self): self.case("explicit_value")
    def test_duplicates(self): self.case("duplicates")
    def test_unresolved_columns(self): self.case("unresolved_columns")
    def test_tooltip_exemption(self): self.case("tooltip_exemption")
    def test_null_is_missing(self): self.case("null_is_missing")
    def test_nonfinite(self): self.case("nonfinite")
    def test_negative_bars_expand_axis(self): self.case("negative_bars_expand_axis")
    def test_line_axis_expands(self): self.case("line_axis_expands")
    def test_scatter_clamps_overflow(self): self.case("scatter_clamps_overflow")
    def test_facets_shared_scale(self): self.case("facets_shared_scale")
    def test_rows_and_state_are_immutable(self): self.case("rows_and_state_are_immutable")
    def test_colors_stable_and_controls_rerender(self): self.case("colors_stable_and_controls_rerender")
    def test_show_numbers_and_focus_tooltip(self): self.case("show_numbers_and_focus_tooltip")
    def test_bookmark_and_theme(self): self.case("bookmark_and_theme")
    def test_scatter_repeated_observations_and_explicit_identity(self): self.case("scatter_repeated_observations_and_explicit_identity")
    def test_nonfinite_tooltip_and_table(self): self.case("nonfinite_tooltip_and_table")
    def test_irrelevant_controls_do_not_rerender(self): self.case("irrelevant_controls_do_not_rerender")
    def test_stable_declared_series_when_other_series_absent(self): self.case("stable_declared_series_when_other_series_absent")
    def test_change_callbacks_unsubscribe(self): self.case("change_callbacks_unsubscribe")
    def test_dynamic_scatter_axes_and_zone_leave_spec_unchanged(self): self.case("dynamic_scatter_axes_and_zone_leave_spec_unchanged")
    def test_responsive_width_stacks_facets_and_preserves_focus_and_numbers(self): self.case("responsive_width_stacks_facets_and_preserves_focus_and_numbers")


if __name__ == "__main__":
    unittest.main()
