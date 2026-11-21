#!/usr/bin/env bash
# Build the native macOS app and .dmg.
#
# Assembles four things the Tauri shell expects under Contents/Resources, then
# hands off to `tauri build`, then signs. Each step is skippable via env so a
# rebuild after a Rust-only change does not re-freeze Python (the slow part).
#
#   backend/  PyInstaller --onedir freeze of api/
#   web/      the built SPA — served BY the backend, not by Tauri
#   models/   the embedding model, so a first run works offline
#   bin/      ripgrep; ffmpeg/ffprobe if you supply them (see below)
#   seed/     the shipped help doc
#
# ffmpeg is NOT fetched by this script. Static macOS builds come from
# individual maintainers' sites, and silently baking a third-party binary into
# something you hand to other people is a supply-chain decision for a human to
# make, not a build script. Drop `ffmpeg` and `ffprobe` into
# desktop/src-tauri/resources/bin/ and they will be bundled and signed with
# everything else. Without them the app runs fine and the capability layer
# reports transcription as unavailable.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$REPO/desktop"
RES="$DESKTOP/src-tauri/resources"
PY="${PILLAR43_BUILD_PYTHON:-/opt/homebrew/bin/python3.12}"
VENV="${PILLAR43_BUILD_VENV:-$REPO/.build-venv}"

step() { printf '\n\033[1m══ %s\033[0m\n' "$1"; }

# Clear any ambient PYTHONPATH. This machine exports
# /opt/homebrew/lib/python3.13/site-packages, which leaks into every 3.12 venv
# and makes pip report transitive deps as "already satisfied" while they are
# invisible to a build that sets PYTHONPATH itself — certifi went missing
# exactly that way, and the model fetch failed silently because its output was
# redirected. A build must not depend on the shell it was launched from.
unset PYTHONPATH

step "1/7  Frontend"
if [ "${SKIP_WEB:-0}" = "1" ]; then echo "  skipped (SKIP_WEB=1)"; else
  (cd "$REPO/web" && npm run build >/dev/null)
  echo "  web/dist built"
fi

# ── Pinned interpreter ────────────────────────────────────────────────────
# python-build-standalone: a CPython built to run from an arbitrary path.
# Homebrew's interpreter hardcodes its install prefix and will not run from
# Contents/Resources, which is why this is a separate download rather than a
# copy of the build machine's Python.
#
# Pinned and hash-checked for the same reason this script refuses to fetch
# ffmpeg: a third-party binary going into something you hand to other people is
# a decision a human makes once, not a moving target a build resolves. Upstream
# publishes no .sha256 sidecar, so the digest below was recorded by hand on
# 2026-08-19 and must be updated deliberately alongside PY_VERSION.
PY_VERSION="3.12.14"
PY_RELEASE="20260814"
PY_ASSET="cpython-${PY_VERSION}+${PY_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/${PY_ASSET}"
PY_SHA256="4572133a5542f306b9bdb155da5800f9e38950cd0a98d469b832ce256fe299ea"
PY_CACHE="$DESKTOP/.tools/$PY_ASSET"
PY_SMOKE_BOOT="$REPO/scripts/smoke-desktop-boot.py"

step "2/7  Backend interpreter + source"
# Replaced PyInstaller on 2026-08-19. Not a preference: Norton's Avast engine
# quarantines the PyInstaller bootloader as MacOS:MalwareX-gen [Spy] — a proven
# false positive (a frozen `print("hello world")` gets the identical verdict)
# that nonetheless killed four consecutive builds mid-freeze, and folder
# exclusions did not take. The bootloader is byte-identical across every
# PyInstaller app including the malware samples the signature was trained on,
# and its stub-plus-opaque-archive shape is what a packer heuristic looks for.
# A plain interpreter has neither. See plans/EMBEDDED_CPYTHON_SIDECAR.md.
if [ "${SKIP_FREEZE:-0}" = "1" ]; then echo "  skipped (SKIP_FREEZE=1)"; else
  mkdir -p "$DESKTOP/.tools"
  if [ ! -f "$PY_CACHE" ]; then
    echo "  fetching CPython $PY_VERSION"
    curl -fsSL "$PY_URL" -o "$PY_CACHE.tmp" && mv "$PY_CACHE.tmp" "$PY_CACHE"
  fi
  GOT="$(shasum -a 256 "$PY_CACHE" | cut -d" " -f1)"
  if [ "$GOT" != "$PY_SHA256" ]; then
    echo "  ERROR: CPython digest mismatch — refusing to build." >&2
    echo "    expected $PY_SHA256" >&2
    echo "    got      $GOT" >&2
    rm -f "$PY_CACHE"
    exit 1
  fi

  rm -rf "$RES/python" "$RES/backend"
  mkdir -p "$RES"
  tar xzf "$PY_CACHE" -C "$RES"        # extracts a `python/` directory
  PYBIN="$RES/python/bin/python3.12"
  [ -x "$PYBIN" ] || { echo "  ERROR: no interpreter at $PYBIN" >&2; exit 1; }

  # --only-binary=:all: rather than letting pip fall back to an sdist. numpy,
  # onnxruntime and pillow-heif publish macosx_14_0_arm64 wheels; onnxruntime
  # has no usable sdist at all, so a silent fallback here is a build that
  # either takes an hour compiling or fails deep inside a compiler. Fail fast.
  echo "  installing dependencies"
  "$PYBIN" -m pip install --only-binary=:all: -q \
      -r "$REPO/api/requirements-desktop.txt" 2>&1 | tail -3

  # ── The application source ────────────────────────────────────────────────
  # Layout mirrors the repo (backend_main.py beside an `api/` sibling) so that
  # backend_main.py's own `../api` sys.path insert resolves identically in the
  # bundle and in a dev checkout. main.rs also sets PYTHONPATH explicitly; the
  # two agree, and neither is load-bearing on its own.
  mkdir -p "$RES/backend/app" "$RES/backend/api"
  cp "$DESKTOP/backend_main.py" "$RES/backend/app/backend_main.py"

  # alembic.ini and migrations/ are NOT optional and NOT env-overridable:
  # services/db.py:32-34 derives both from `Path(__file__).parent.parent`. Ship
  # them or init_schema() fails at main.py:181 — which is caught and logged
  # without stopping startup, so the app boots and every query fails after.
  # seed/ matters less (main.rs sets PILLAR43_HELP_SEED) but makes
  # help_docs.py's fallback correct for the first time.
  #
  # tests/ and scripts/ are excluded deliberately. scripts/ also collides with a
  # stray `scripts/` directory shipped by google-api-python-client, and api/ goes
  # on sys.path[0].
  (cd "$REPO/api" && tar cf - \
      --exclude='__pycache__' --exclude='*.pyc' \
      main.py config.py alembic.ini \
      models routes services migrations) | (cd "$RES/backend/api" && tar xf -)

  bash "$REPO/scripts/prune-desktop-python.sh" "$RES/python"
  "$PYBIN" "$REPO/scripts/smoke-desktop-python.py" || {
    echo "  ERROR: bundled interpreter failed its smoke test — see above." >&2
    exit 1
  }
  echo "  backend staged (python $(du -sh "$RES/python" | cut -f1), source $(du -sh "$RES/backend" | cut -f1))"
fi

step "3/7  Resources"
rm -rf "$RES/web"
mkdir -p "$RES/web" "$RES/bin" "$RES/models"
cp -R "$REPO/web/dist/." "$RES/web/"

# ripgrep: built from source rather than downloaded as a prebuilt binary —
# same supply chain as the rest of the Rust toolchain, and Homebrew's copy is
# not relocatable (it links libpcre2 out of /opt/homebrew).
if [ ! -x "$RES/bin/rg" ]; then
  echo "  building ripgrep from source (once)…"
  cargo install ripgrep --root "$DESKTOP/.tools" --quiet
  cp "$DESKTOP/.tools/bin/rg" "$RES/bin/rg"
fi
for opt in ffmpeg ffprobe; do
  [ -x "$RES/bin/$opt" ] && echo "  bundling $opt" || echo "  no $opt — transcription will report unavailable"
done

# Embedding model. Pulled once into the build tree via the app's own code path,
# so what ships is exactly what it would have downloaded at runtime.
# `ls -A` would count a .gitkeep as content and silently skip the fetch,
# shipping an app that downloads 64MB on first run instead of working offline.
if [ -z "$(find "$RES/models" -mindepth 1 -name "*.onnx" -print -quit 2>/dev/null)" ]; then
  echo "  fetching the embedding model (once)…"
  # Not silenced: a failure here ships an app that downloads 64MB on first
  # run instead of working offline, and that is not something to discover
  # from a tester.
  FASTEMBED_CACHE_PATH="$RES/models" PYTHONPATH="$REPO/api" \
    "$VENV/bin/python" -c "
from services import embeddings
embeddings.embed_query('warm the cache')
" 2>&1 | grep -vE "Fetching|it/s|HF_TOKEN|Xet|cpuid" | tail -2
  if ! find "$RES/models" -name "*.onnx" -print -quit | grep -q .; then
    echo "  ERROR: model fetch produced no .onnx — refusing to ship a bundle that
  needs the network on first launch." >&2
    exit 1
  fi
fi
echo "  resources staged ($(du -sh "$RES" | cut -f1))"

# ── Signing configuration ─────────────────────────────────────────────────
# APPLE_SIGNING_IDENTITY: the full identity string, e.g.
#   "Developer ID Application: Jane Smith (AB12CD34EF)"
# `security find-identity -v -p codesigning` lists what is installed.
#
# Unset (the default) keeps the ad-hoc path this script has always used: the
# app runs on the machine that built it and nowhere else without the user
# stripping the quarantine bit by hand. Ad-hoc builds CANNOT be notarized —
# the notary service requires a Developer ID signature, the hardened runtime,
# and a secure timestamp, and ad-hoc has none of the three.
SIGN_ID="${APPLE_SIGNING_IDENTITY:-}"
ENTITLEMENTS="$DESKTOP/src-tauri/entitlements.plist"

if [ -n "$SIGN_ID" ]; then
  # --options runtime and --timestamp are BOTH required by the notary service.
  # The ad-hoc path's --timestamp=none is a hard notarization failure, which is
  # why the two paths cannot share one flag set.
  SIGN_DESC="Developer ID"
  [ -f "$ENTITLEMENTS" ] || { echo "  ERROR: entitlements missing at $ENTITLEMENTS" >&2; exit 1; }
else
  SIGN_DESC="ad-hoc"
fi

step "4/7  Bundle the .app"
# ── Gates on the artifact itself ──────────────────────────────────────────
# Every other gate in this repo runs against Docker: ./scripts/test-api execs
# pytest in the test container, and no CI workflow builds this app at all. So
# the bundle — the thing users actually run — had no coverage of its own, and
# it showed: it shipped with openai==1.54.3 against httpx==0.28.1, which
# removed the `proxies` kwarg those releases pass, leaving EVERY
# openai-compatible provider dead at client construction while all 1,827
# backend tests stayed green.
#
# Three gates, cheapest first, each catching something the others cannot:
#
#   cargo test            the vault-path precedence table (src/paths.rs) and
#                         the generated menu model — shell logic no Python
#                         test can see
#   test-desktop-bundle   the backend suite against the BUNDLED interpreter.
#                         Source is copied verbatim from api/, so what differs
#                         between Docker and the app is the dependency set —
#                         which is exactly what this exercises
#   smoke-desktop-boot    actually starts the backend. The other two would
#                         pass on a build whose migration chain fails, whose
#                         validate_startup rejects its own mounts, or that has
#                         a router importing a name that no longer exists
#
# SKIP_TESTS=1 to skip all three, for tight Rust/UI loops.
if [ "${SKIP_TESTS:-0}" != "1" ]; then
  echo "  cargo test"
  (cd "$DESKTOP/src-tauri" && cargo test --quiet 2>&1 | tail -5)
  echo "  backend suite against the bundled interpreter"
  "$REPO/scripts/test-desktop-bundle" 2>&1 | tail -6
  "$PY_SMOKE_BOOT" 2>&1 | tail -12
fi
# .app only. The .dmg is built afterwards, from the SIGNED app — Tauri's
# combined `--bundles app,dmg` produces the image before any signing step can
# run, which ships a disk image containing an unsigned bundle. On Apple
# Silicon that is not a nitpick: an unsigned binary will not execute at all.
(cd "$DESKTOP" && ./node_modules/.bin/tauri build --bundles app 2>&1 | tail -3)

APP="$DESKTOP/src-tauri/target/release/bundle/macos/Pillar-43.app"

step "5/7  Sign ($SIGN_DESC, inside-out)"
# On Apple Silicon every executable needs at least an ad-hoc signature to run
# at all, and PyInstaller rewrites its output after its constituent libraries
# were signed — so every embedded binary is re-signed from the inside out
# before the .app itself. Skipping this produces "damaged and can't be opened".
if [ -z "$SIGN_ID" ]; then
  # Unchanged from the original. Proven; do not "improve" it while it is the
  # path every local build takes.
  find "$APP" \( -name "*.dylib" -o -name "*.so" \) -print0 \
    | xargs -0 -n1 codesign --force --timestamp=none -s - 2>/dev/null || true
  # The interpreter replaced the `backend/pillar43-backend` stub this loop used
  # to name (2026-08-19). The Developer ID path below needed no such edit — it
  # finds Mach-O files by content rather than by name, which is why it is the
  # one that keeps working when the layout changes.
  for b in "$APP/Contents/Resources/bin/"* "$APP/Contents/Resources/python/bin/"*; do
    [ -f "$b" ] && codesign --force --timestamp=none -s - "$b" 2>/dev/null || true
  done
  codesign --force --deep --timestamp=none -s - "$APP"
else
  # --deep is NOT used here. Apple documents it as unsuitable for distribution
  # signing (it applies the outer bundle's entitlements to nested code and
  # skips things it does not recognise), and notarization rejects bundles it
  # produced. The cost of dropping it is that we must find every Mach-O
  # ourselves — including the ones the ad-hoc path's *.dylib/*.so glob misses,
  # such as Python.framework/Versions/3.12/Python, which carries no extension
  # and was only ever signed because --deep swept it up.
  echo "  identity: $SIGN_ID"
  MACHO_LIST="$(mktemp)"
  # `file` reports a UNIVERSAL binary three times: once for the file, then once
  # per architecture with a " (for architecture arm64)" suffix glued to the
  # path. Left in, those two become paths that do not exist, and codesign fails
  # on them — which is harmless in itself (the clean line signs the file) but
  # produced ten warnings per build about files that were signed correctly.
  # A warning channel that cries wolf is worse than none, because a real
  # failure then looks exactly like the noise. Strip the suffix and dedupe.
  find "$APP" -type f -perm -u+r -print0 \
    | xargs -0 file --mime-type 2>/dev/null \
    | grep -E ':[[:space:]]*application/x-mach-binary$' \
    | sed -E 's/:[[:space:]]*application\/x-mach-binary$//; s/ \(for architecture [^)]*\)$//' \
    | sort -u > "$MACHO_LIST"
  echo "  signing $(wc -l < "$MACHO_LIST" | tr -d ' ') Mach-O files inside-out"

  # Deepest paths first: a nested binary must be signed before whatever
  # contains it, or the container's seal is invalidated the moment the inner
  # one changes.
  awk '{ print gsub(/\//,"/") "\t" $0 }' "$MACHO_LIST" | sort -rn | cut -f2- \
    | while IFS= read -r f; do
        codesign --force --options runtime --timestamp -s "$SIGN_ID" \
                 --entitlements "$ENTITLEMENTS" "$f" >/dev/null 2>&1 || {
          echo "  WARNING: could not sign $f" >&2; }
      done
  rm -f "$MACHO_LIST"

  codesign --force --options runtime --timestamp -s "$SIGN_ID" \
           --entitlements "$ENTITLEMENTS" "$APP"
fi
codesign --verify --verbose=1 "$APP" 2>&1 | tail -2

step "6/7  Disk image"
# Built by hand rather than through Tauri's bundle_dmg.sh, which drives Finder
# over AppleScript to lay the window out. That needs automation permission, it
# mounts the volume while it works, and a mount that anything touches refuses
# to detach — the first attempt here wedged on exactly that. hdiutil straight
# from a staging directory has none of those moving parts.
DMGDIR="$DESKTOP/src-tauri/target/release/bundle/dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir -p "$DMGDIR"
DMG="$DMGDIR/Pillar-43_0.1.0_aarch64.dmg"
rm -f "$DMG"
hdiutil create -volname Pillar-43 -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
if [ -z "$SIGN_ID" ]; then
  codesign --force --timestamp=none -s - "$DMG" 2>/dev/null || true
else
  codesign --force --timestamp -s "$SIGN_ID" "$DMG"
fi

step "7/7  Notarize"
# Notarization is Apple scanning the artifact and issuing a ticket. `staple`
# then attaches that ticket to the .dmg so Gatekeeper can verify it OFFLINE —
# without stapling, a tester with no network sees the same warning as an
# unnotarized build.
#
# Credentials, in preference order:
#   NOTARY_PROFILE   — a keychain profile name, created once with:
#                        xcrun notarytool store-credentials "pillar43-notary" \
#                          --apple-id you@example.com --team-id ABCD123456 \
#                          --password <app-specific-password>
#                      Preferred: the password never appears in a shell
#                      history, a CI log, or this script's environment.
#   APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD — the explicit form, for CI.
#
# APPLE_APP_PASSWORD is an app-specific password from appleid.apple.com, NOT
# the Apple ID password. The real password is rejected.
if [ -z "$SIGN_ID" ]; then
  echo "  skipped — ad-hoc builds cannot be notarized (set APPLE_SIGNING_IDENTITY)"
elif [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "  submitting via keychain profile '$NOTARY_PROFILE' (this takes minutes)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  echo "  submitting as $APPLE_ID (this takes minutes)"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
else
  echo "  skipped — signed but no notarization credentials"
  echo "    set NOTARY_PROFILE, or APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD"
fi

echo
echo "  app: $APP  ($(du -sh "$APP" | cut -f1))"
echo "  dmg: $DMG  ($(du -sh "$DMG" | cut -f1))"
echo
if [ -z "$SIGN_ID" ]; then
  echo "  Testers: this is ad-hoc signed, not notarized. After downloading,"
  echo "    xattr -dr com.apple.quarantine /Applications/Pillar-43.app"
  echo "  or System Settings → Privacy & Security → Open Anyway."
else
  echo "  Verify what a tester will actually get:"
  echo "    spctl -a -vvv -t install \"$APP\""
  echo "  Expect: \"accepted, source=Notarized Developer ID\". Anything else"
  echo "  means they will still see a warning — check it before shipping."
fi
