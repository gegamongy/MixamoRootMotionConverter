"""
Batch Root Motion Extractor
============================
With an armature selected, finds every action whose name contains
"walk", "run", or "sprint" (case-insensitive), sets each as the active
action, and runs extract_root_motion() from the converter script.

Usage:
  1. Select your armature in the viewport.
  2. Optionally add more name filters to FILTER_KEYWORDS below.
  3. Run the script.
"""

import importlib.util
import sys
import bpy

# ═══════════════════════════ CONFIG ════════════════════════════
CONVERTER_PATH  = "/Users/quinn/MixamoRootMotionConverter/mixamo_root_motion_converter.py"

# Actions whose names contain ANY of these strings will be processed.
# Matching is case-insensitive.
FILTER_KEYWORDS = ["walk", "run", "sprint"]
# ═══════════════════════════════════════════════════════════════


def load_converter():
    """Import the converter script as a module without executing its
    top-level extract_root_motion() call (that call is guarded below)."""
    spec   = importlib.util.spec_from_file_location("mixamo_root_motion_converter", CONVERTER_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so any internal imports resolve correctly.
    sys.modules["mixamo_root_motion_converter"] = module
    spec.loader.exec_module(module)
    return module


def batch_extract() -> None:
    obj = bpy.context.active_object
    if obj is None or obj.type != "ARMATURE":
        raise ValueError("No armature is active. Select your armature and try again.")

    # Load the converter and override its ARMATURE_NAME to match the
    # currently selected object (handles renames without editing the converter).
    converter = load_converter()
    converter.ARMATURE_NAME = obj.name

    if obj.animation_data is None:
        obj.animation_data_create()

    keywords_lower = [kw.lower() for kw in FILTER_KEYWORDS]

    matching = [
        action for action in bpy.data.actions
        if any(kw in action.name.lower() for kw in keywords_lower)
    ]

    if not matching:
        print(f"No actions found matching keywords: {FILTER_KEYWORDS}")
        return

    print(f"Found {len(matching)} matching action(s):")
    for a in matching:
        print(f"  • {a.name}")
    print()

    original_action = obj.animation_data.action
    succeeded = []
    failed    = []

    for action in matching:
        print(f"{'─' * 60}")
        print(f"Processing: {action.name}")
        obj.animation_data.action = action
        bpy.context.view_layer.update()

        try:
            converter.extract_root_motion()
            succeeded.append(action.name)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            failed.append((action.name, str(exc)))

    # Restore the original action
    obj.animation_data.action = original_action

    print(f"\n{'═' * 60}")
    print(f"Batch complete.  {len(succeeded)} succeeded, {len(failed)} failed.")
    if failed:
        print("Failed actions:")
        for name, err in failed:
            print(f"  ✗ {name}: {err}")


batch_extract()
