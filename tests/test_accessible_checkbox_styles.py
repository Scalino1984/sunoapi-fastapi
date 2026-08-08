from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_global_checkboxes_have_unambiguous_accessible_states():
    css = (ROOT / "frontend-react/src/styles/app.css").read_text(encoding="utf-8")

    assert 'input[type="checkbox"] {' in css
    assert '-webkit-appearance: none' in css
    assert 'width: 22px !important' in css
    assert 'input[type="checkbox"]:checked {' in css
    assert "stroke='%23ffffff'" in css
    assert 'input[type="checkbox"]:indeterminate {' in css
    assert 'input[type="checkbox"]:focus-visible {' in css
    assert '@media (forced-colors: active)' in css
    assert 'label.check-row:has(input[type="checkbox"]:checked)' in css
