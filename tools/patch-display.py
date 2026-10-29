#!/usr/bin/env python3
"""Patch the SPRD display + Himax touch drivers for the Tab A8 panel.

Two independent bugs on the stock Samsung 4.14 tree make the display go black
as soon as a real Wayland compositor starts:

1. sprd_plane_atomic_update() bails out whenever the CRTC's ``active_changed``
   flag is set.  A compositor's first atomic commit after mode-set normally
   changes ``active`` together with the plane contents, so the layer is never
   programmed into the DPU and the panel keeps scanning out an empty layer.

2. The Himax hx83102e touch driver toggles its reset GPIO on every runtime
   reset.  On this board that line is shared with the panel reset, so a touch
   reset while the DSI link is streaming blanks the display.  After probe the
   controller is already initialised, so the runtime resets must not happen.

Run from the kernel tree root.  The script is idempotent and refuses to claim
success if a pattern it expects is missing.
"""
import re
import sys
from pathlib import Path

DPU_FILES = [
    Path("drivers/gpu/drm/sprd/sprd_dpu.c"),
    Path("drivers/gpu/drm/sprd/sprd_dpu1.c"),
]

DPU_EARLY_RETURN = re.compile(
    r"[ \t]*if \(plane->state->crtc->state->active_changed\) \{\n"
    r"[ \t]*DRM_DEBUG\(\"resume or suspend, no need to update plane\\n\"\);\n"
    r"[ \t]*return;\n"
    r"[ \t]*\}\n"
)

DPU_GUARD = """	/*
	 * GTA8: do not skip the plane update on a CRTC active change.
	 *
	 * The vendor code returns here, but a compositor's first commit after
	 * a mode-set usually flips active together with the plane state.  The
	 * layer then never reaches the DPU and the panel stays black.  Only
	 * the disabled-plane case really has nothing to program.
	 */
	if (!state->crtc || !fb) {
		DRM_DEBUG("plane has no CRTC/framebuffer, nothing to update\\n");
		return;
	}
"""

HIMAX_RESETS = [
    (
        Path("drivers/input/touchscreen/Tab_A8/hxchipset/himax_ic_incell_core.c"),
        "himax_mcu_pin_reset",
    ),
    (
        Path("drivers/input/touchscreen/Tab_A8/hxchipset/himax_ic_HX83102.c"),
        "hx83102_pin_reset",
    ),
]

HIMAX_GUARD = """	/*
	 * GTA8: the touch reset line is shared with the panel on this board.
	 * Toggling it after probe resets the panel while DSI keeps streaming,
	 * which shows up as a black screen.  Probe still performs the initial
	 * reset; runtime resets are intentionally skipped.
	 */
	if (g_hx_chip_inited) {
		I("%s: post-probe reset skipped (shared panel reset line)\\n",
			__func__);
		return;
	}
"""


def patch_dpu(path: Path) -> bool:
    text = path.read_text()
    if "GTA8: do not skip the plane update" in text:
        print(f"[skip] {path}: already patched")
        return True

    # Use a callable: re.sub() would interpret the \n in the C string as an
    # escape and turn it into a real newline.
    new, count = DPU_EARLY_RETURN.subn(lambda _m: DPU_GUARD, text)
    if count != 1:
        print(
            f"[FAIL] {path}: found {count} active_changed early-return blocks "
            "(want 1). The kernel tree does not look like the expected tree.",
            file=sys.stderr,
        )
        return False

    path.write_text(new)
    print(f"[ok] {path}: removed active_changed plane-update guard")
    return True


def patch_himax(path: Path, func: str) -> bool:
    text = path.read_text()
    if "GTA8: the touch reset line is shared" in text:
        print(f"[skip] {path}: already patched")
        return True

    signature = re.compile(
        r"(static void %s\(void\)\n\{\n)" % re.escape(func)
    )
    if not signature.search(text):
        print(
            f"[FAIL] {path}: {func}() not found; check the kernel tree",
            file=sys.stderr,
        )
        return False

    new, count = signature.subn(
        lambda m: m.group(1) + HIMAX_GUARD, text, count=1
    )
    if count != 1:
        print(f"[FAIL] {path}: could not insert guard in {func}()", file=sys.stderr)
        return False

    path.write_text(new)
    print(f"[ok] {path}: guarded {func}()")
    return True


def main() -> int:
    if not Path("drivers/gpu/drm/sprd").is_dir():
        print(
            "run this from the kernel tree root (drivers/gpu/drm/sprd missing)",
            file=sys.stderr,
        )
        return 2

    ok = True
    for path in DPU_FILES:
        if not path.is_file():
            print(f"[FAIL] missing {path}", file=sys.stderr)
            ok = False
            continue
        ok = patch_dpu(path) and ok

    for path, func in HIMAX_RESETS:
        if not path.is_file():
            print(f"[FAIL] missing {path}", file=sys.stderr)
            ok = False
            continue
        ok = patch_himax(path, func) and ok

    if not ok:
        print("display patch failed", file=sys.stderr)
        return 1

    print("display patches applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
