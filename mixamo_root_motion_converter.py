"""
Root Motion Extractor for Mixamo Animations in Blender
=======================================================
Extracts horizontal world-space translation from the hips bone and
transfers it to the root bone, then removes it from the hips.

Usage:
  1. Open this script in Blender's Text Editor (or paste into the Python console).
  2. Adjust the CONFIG section below.
  3. Press "Run Script".
"""

import bpy
import mathutils  # noqa: F401  (imported via bpy namespace, kept for clarity)


# ═══════════════════════════ CONFIG ════════════════════════════
ARMATURE_NAME  = "Player"         # Name of the armature object in the scene
ROOT_BONE_NAME = "Root"             # Root bone (receives the extracted motion)
HIPS_BONE_NAME = "mixamorig:Hips"  # Hips bone (source of baked root motion)

EXTRACT_X = True   # Move world-X motion from hips → root
EXTRACT_Y = True   # Move world-Y motion from hips → root
EXTRACT_Z = False  # Keep world-Z (vertical) on hips; set True to also extract height
# ═══════════════════════════════════════════════════════════════


def extract_root_motion() -> None:
    scene = bpy.context.scene
    obj   = bpy.data.objects.get(ARMATURE_NAME)

    if obj is None or obj.type != "ARMATURE":
        raise ValueError(f"Armature '{ARMATURE_NAME}' not found or is not an armature.")

    # Switch to Pose Mode so pose-bone matrices are accessible
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="POSE")

    root_pb = obj.pose.bones.get(ROOT_BONE_NAME)
    hips_pb = obj.pose.bones.get(HIPS_BONE_NAME)

    if root_pb is None:
        raise ValueError(f"Bone '{ROOT_BONE_NAME}' not found in '{ARMATURE_NAME}'.")
    if hips_pb is None:
        raise ValueError(f"Bone '{HIPS_BONE_NAME}' not found in '{ARMATURE_NAME}'.")

    # Determine frame range from the action's keyframes rather than the
    # scene in/out points, so short animations don't scrub empty frames.
    anim_data = obj.animation_data
    if anim_data and anim_data.action and anim_data.action.fcurves:
        all_keys = [
            kp.co.x
            for fc in anim_data.action.fcurves
            for kp in fc.keyframe_points
        ]
        frame_start = int(min(all_keys))
        frame_end   = int(max(all_keys))
        print(f"    Action keyframe range detected: {frame_start}–{frame_end}")
    else:
        frame_start = scene.frame_start
        frame_end   = scene.frame_end
        print(f"    No action keyframes found; falling back to scene range: {frame_start}–{frame_end}")

    frames = range(frame_start, frame_end + 1)

    # obj.matrix_world stays constant (we only edit bone poses, not the object).
    obj_mat_inv = obj.matrix_world.inverted()

    # ── Pass 1: Sample world-space matrices for every frame ──────────────────
    # We must read ALL frames BEFORE writing anything, because modifying the
    # action during playback would corrupt later samples.
    print(f"[1/3] Sampling world matrices for {len(frames)} frames…")

    hips_world_per_frame: dict[int, object] = {}
    root_world_per_frame: dict[int, object] = {}

    for f in frames:
        scene.frame_set(f)
        # pose_bone.matrix is in armature-local space; multiply by obj.matrix_world
        # to obtain the bone's true world-space 4×4 matrix.
        hips_world_per_frame[f] = (obj.matrix_world @ hips_pb.matrix).copy()
        root_world_per_frame[f] = (obj.matrix_world @ root_pb.matrix).copy()

    # ── Pass 2: Remove stale location FCurves for both bones ─────────────────
    # This prevents leftover keyframes (outside frame_start/end) from
    # interfering with the newly written ones.
    print("[2/3] Clearing old location keyframes for Root and Hips…")

    if anim_data and anim_data.action:
        action       = anim_data.action
        root_prefix  = f'pose.bones["{ROOT_BONE_NAME}"]'
        hips_prefix  = f'pose.bones["{HIPS_BONE_NAME}"]'
        stale = [
            fc for fc in action.fcurves
            if (root_prefix in fc.data_path or hips_prefix in fc.data_path)
            and "location" in fc.data_path
        ]
        for fc in stale:
            action.fcurves.remove(fc)
        print(f"    Removed {len(stale)} stale location FCurve(s).")
    else:
        print("    No active action found on armature — location keyframes will be created fresh.")

    # ── Pass 3: Apply & keyframe the new transforms ──────────────────────────
    print("[3/3] Applying root motion and inserting keyframes…")

    progress_step = max(1, len(frames) // 10)  # print roughly every 10 %

    for i, f in enumerate(frames):
        scene.frame_set(f)

        h_world = hips_world_per_frame[f]
        r_world = root_world_per_frame[f]

        # ── Step A: Build the new root world matrix ──────────────────────────
        # Keep root's world rotation; only update the translation axes we care about.
        new_root_translation = r_world.translation.copy()
        if EXTRACT_X:
            new_root_translation.x = h_world.translation.x
        if EXTRACT_Y:
            new_root_translation.y = h_world.translation.y
        if EXTRACT_Z:
            new_root_translation.z = h_world.translation.z

        new_r_world = r_world.copy()
        new_r_world.translation = new_root_translation

        # Convert from world space → armature-local space, then assign.
        # Blender decomposes this into root_pb.location / rotation_* / scale.
        root_pb.matrix = obj_mat_inv @ new_r_world

        # Propagate so child bones (including Hips) see the updated Root position.
        bpy.context.view_layer.update()

        # ── Step B: Restore hips to its original world matrix ────────────────
        # Because Root moved, Hips' world position changed too. Setting hips_pb.matrix
        # back to the sampled value makes Blender recalculate the correct local offset
        # so Hips ends up exactly where it was before — no visible body movement.
        hips_pb.matrix = obj_mat_inv @ h_world

        # Propagate once more so keyframe_insert reads the settled values.
        bpy.context.view_layer.update()

        # ── Step C: Insert location keyframes (rotations are left untouched) ─
        root_pb.keyframe_insert(data_path="location", frame=f)
        hips_pb.keyframe_insert(data_path="location", frame=f)

        if i % progress_step == 0:
            pct = int(100 * i / len(frames))
            print(f"    {pct:3d}%  (frame {f})")

    # Return to the first frame for a clean viewport state.
    scene.frame_set(frame_start)

    print(
        f"\nDone! Root motion extracted across {len(frames)} frames "
        f"({frame_start}–{frame_end}).\n"
        f"  Root  → now carries world {'X' if EXTRACT_X else ''}{'Y' if EXTRACT_Y else ''}{'Z' if EXTRACT_Z else ''} translation.\n"
        f"  Hips  → local translation zeroed out on those axes."
    )


# ── Entry point ──────────────────────────────────────────────────────────────
extract_root_motion()
