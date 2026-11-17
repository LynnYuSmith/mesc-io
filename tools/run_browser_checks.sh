#!/usr/bin/env bash
# The viewer's real-browser checks (tests/*_real_chrome.js), one after another, each against a
# fresh `mesc-io view` on a synthetic file with its own empty HOME (the viewer keeps ROIs and the
# view in ~/mesc-viewer/, and a check must not see what the previous one drew).
#
#   tools/run_browser_checks.sh                 # all deterministic checks
#   tools/run_browser_checks.sh view_zstack     # only the ones whose name contains this
#
# Needs Node >= 22 (global WebSocket) and Chrome; CHROME=/path/to/chrome overrides the macOS
# default. Left out: explore_real_chrome.js (a seeded monkey, for before a release),
# view_shots_real_chrome.js (screenshots for the README), and view_playback_real_chrome.js and
# view_metadata_real_chrome.js (need a real recording: the synthetic file has 7 metadata rows). Exit status: the number of failed checks (0 = all passed).
set -u
ONLY="${1:-}"
PY="${PYTHON:-python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="$(mktemp -d "${TMPDIR:-/tmp}/mesc_io_browser.XXXXXX")"
trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$W"' EXIT
mkdir -p "$W/out"

( cd "$W" && "$PY" "$ROOT/tools/make_synthetic.py" >/dev/null \
          && "$PY" "$ROOT/tools/make_synthetic.py" --stack >/dev/null \
          && "$PY" "$ROOT/tools/make_synthetic.py" --mosaic >/dev/null ) || { echo "synthetic files failed"; exit 99; }

file_of() { echo "$W/synthetic_$1.mesc"; }   # view | stack | mosaic (bash 3.2 has no maps)

# Every check starts Chrome with a fresh profile. On macOS a fresh profile asks the login
# keychain for "Chrome Safe Storage" (a password prompt per check); a mock keychain keeps it
# away. CHROME_EXTRA_FLAGS adds more (CI on Linux: --no-sandbox).
REAL_CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
cat >"$W/chrome" <<EOF
#!/bin/sh
exec "$REAL_CHROME" --use-mock-keychain --password-store=basic ${CHROME_EXTRA_FLAGS:-} "\$@"
EOF
chmod +x "$W/chrome"
export CHROME="$W/chrome"

serve() {  # serve <file key> <port> <home>  → waits until the viewer answers
  mkdir -p "$3"
  HOME="$3" "$PY" -m mesc_io view "$(file_of "$1")" --port "$2" --no-browser >"$3/viewer.log" 2>&1 &
  for _ in $(seq 1 100); do
    curl -sf "http://127.0.0.1:$2/" >/dev/null 2>&1 && return 0
    sleep 0.2
  done
  echo "viewer on $1 did not come up:"; cat "$3/viewer.log"; return 1
}

FAILED=0; RAN=0
check() {  # check <name> <file key> [second file key]
  local name="$1"
  [[ -n "$ONLY" && "$name" != *"$ONLY"* ]] && return 0
  local home="$W/home_$name" urls="" port=8100 key
  shift
  for key in "$@"; do
    serve "$key" "$port" "$home/$key" || { FAILED=$((FAILED + 1)); return 0; }
    urls="$urls http://127.0.0.1:$port/"; port=$((port + 1))
  done
  RAN=$((RAN + 1))
  local t0=$SECONDS
  if HOME="$home" node "$ROOT/tests/${name}_real_chrome.js" $urls "$W/out/$name" >"$W/out/$name.log" 2>&1; then
    echo "ok    $name ($((SECONDS - t0)) s)"
  else
    FAILED=$((FAILED + 1)); echo "FAIL  $name ($((SECONDS - t0)) s)"; sed 's/^/      /' "$W/out/$name.log" | tail -25
  fi
  kill $(jobs -p) 2>/dev/null; wait 2>/dev/null
}

check view            view
check view_layout     view
check view_fastpaths  view stack
check view_zstack     stack
check view_zstack3d   stack
check view_3dtools    stack
check view_gamma_object stack
check view_modes      stack
check view_surface    stack
check view_no_ghost_rois stack
check view_mosaic     mosaic

echo "$RAN checks, $FAILED failed"
exit "$FAILED"
