"""player.js: playback waits for the disk and loops inside the range; arrows clamp; the time window slides and keeps its width."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "src" / "mesc_io"
PLAYER = PKG / "static" / "player.js"
PAGE = PKG / "viewer.html"
NODE = shutil.which("node")

CHECK = r"""
const vm = require("node:vm"), fs = require("node:fs");
let ticks = [];                                   // a hand-driven timer: the test decides when a tick happens
const sb = { console, setInterval: f => { ticks.push(f); return 7; }, clearInterval: () => { ticks = []; } };
sb.window = sb;
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), vm.createContext(sb));
const P = sb.MescIO.player, out = {};
out.next = [P.nextFrame(3, 2, 5), P.nextFrame(5, 2, 5)];
out.step = [P.stepFrame(0, -1, false, 100), P.stepFrame(98, 1, true, 100), P.stepFrame(50, 1, true, 100)];
out.slide = [P.slideWindow([100, 200], 1, false, 1000), P.slideWindow([100, 200], -1, true, 1000),
             P.slideWindow([850, 950], 1, true, 1000), P.slideWindow([0, 3], -1, false, 1000)];
out.avg = [P.clampAvg("3"), P.clampAvg("0"), P.clampAvg("abc"), P.clampAvg(5000), P.clampAvg(2.6)];
// playback: frame 4 of [2, 5]; the second tick comes while the disk is busy → skipped
let frame = 4, busy = false; const seen = [];
const pl = P.createPlayer(40);
pl.start({ range: [2, 5], frame: () => frame, isBusy: () => busy, onFrame: f => { frame = f; seen.push(f); } });
out.playing_after_start = pl.playing;
ticks[0](); busy = true; ticks[0](); busy = false; ticks[0](); ticks[0]();
out.seen = seen;
pl.stop(); out.playing_after_stop = pl.playing; out.ticks_left = ticks.length;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="node is not on this machine")
def test_player_js(tmp_path):
    js = tmp_path / "c.js"
    js.write_text(CHECK, encoding="utf-8")
    r = subprocess.run([NODE, str(js), str(PLAYER)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["next"] == [4, 2]                                   # one on; past the end → start of the range
    assert o["step"] == [0, 99, 60]                              # clamped at both ends; shift = 10
    assert o["slide"] == [[110, 210], [50, 150], [899, 999], [0, 3]]   # width kept, never past the ends
    assert o["avg"] == [3, 1, 1, 999, 3]
    assert o["playing_after_start"] is True
    assert o["seen"] == [5, 2, 3]                                # the busy tick moved nothing; 5 → 2 loops
    assert o["playing_after_stop"] is False and o["ticks_left"] == 0


def test_page_loads_player_js_with_the_other_modules():
    src = PAGE.read_text(encoding="utf-8")
    order = [src.index(f'<script src="static/{m}.js">') for m in ("api", "image", "player")] + [src.index("<script>")]
    assert order == sorted(order)


def test_viewer_serves_player_js(standalone):
    from test_engine import _get
    _, base, _ = standalone
    code, body = _get(base + "/static/player.js")
    assert code == 200 and body == PLAYER.read_bytes()


from test_engine import standalone  # noqa: E402,F401
