"""Time bands on the traces (16 Nov 2026): a host gives the viewer stimulus epochs through ``_Handler._epochs``.

No host hook → no bands (a plain .mesc looks as before). With a hook → its bands, cleaned (ints, end > start,
label/kind/title strings). A hook that raises → no bands and the reason, never a broken page."""
from mesc_io import viewer as V


def _handler(hook):
    cls = type("H", (V._Handler,), {"_epochs": staticmethod(hook) if hook else None})
    return cls.__new__(cls)


def test_no_hook_no_bands():
    assert _handler(None)._epochs_for("MSession_0/MUnit_1") == {"epochs": []}


def test_hook_bands_are_cleaned():
    seen = []

    def hook(path):
        seen.append(path)
        return [{"start": 201.0, "end": 449, "label": "0°", "kind": "moving"},
                {"start": 500, "end": 500, "label": "empty"},          # zero length: dropped
                {"start": 698, "end": 946, "label": 45}]               # label becomes a string, title defaults to it
    got = _handler(hook)._epochs_for("MSession_0/MUnit_1")["epochs"]
    assert seen == ["MSession_0/MUnit_1"]
    assert got == [{"start": 201, "end": 449, "label": "0°", "kind": "moving", "title": "0°"},
                   {"start": 698, "end": 946, "label": "45", "kind": "", "title": "45"}]


def test_a_broken_hook_does_not_break_the_page():
    def hook(path):
        raise KeyError("events_pulse")
    d = _handler(hook)._epochs_for("MSession_0/MUnit_1")
    assert d["epochs"] == [] and "events_pulse" in d["error"]
