"""
Root Rotation Extractor for Mixamo Animations in Blender
=========================================================
Extracts world-space rotation from the hips bone and transfers it to
the root bone, then removes that rotation from the hips.

Rotation axes refer to world-space Euler XYZ (Blender Z-up):
  X → pitch  (lean forward / backward)
  Y → roll   (lean side to side)
  Z → yaw    (turn left / right)  ← most useful for locomotion

Assumptions:
  - Blender default Z-up coordinate system.
  - Hierarchy: Root  ->  mixamorig:Hips  ->  rest of skeleton.
  - The active action is the one you want to bake (not an NLA strip).
  - Neither bone has constraints that fight the pose (IK targets, etc.).

Usage:
  1. Open this script in Blender's Text Editor (or paste into the Python console).
  2. Adjust the CONFIG section below.
  3. Press "Run Script".
"""

import bpy
import mathutils


# ═══════════════════════════ CONFIG ════════════════════════════
ARMATURE_NAME  = "Player"           # Name of the armature object in the scene
ROOT_BONE_NAME = "Root"             # Root bone (receives the extracted rotation)
HIPS_BONE_NAME = "mixamorig:Hips"  # Hips bone (source of baked root rotation)

EXTRACT_ROT_X = False  # Pitch  – lean forward/backward  (usually keep on hips)
EXTRACT_ROT_Y = False  # Roll   – lean side to side       (usually keep on hips)
EXTRACT_ROT_Z = True   # Yaw    – horizontal turn         (extract for locomotion)

# When True, only the *change* in hips rotation (delta from frame 0) is
# applied on top of the root's original rest rotation, so the root stays
# in its authored position and receives only the animation offset.
# When False (default), the hips rotation is copied directly to the root.
ADDITIVE_MODE = True
# ═══════════════════════════════════════════════════════════════


def _rotation_data_path(pose_bone) -> str:
    """Return the correct rotation data_path for keyframe_insert."""
    mode = pose_bone.rotation_mode
    if mode == "QUATERNION":
        return "rotation_quaternion"
    if mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def extract_root_rotation() -> None:
    scene = bpy.context.scene
    obj   = bpy.data.objects.get(ARMATURE_NAME)

    if obj is None or obj.type != "ARMATURE":
        raise ValueError(f"Armature '{ARMATURE_NAME}' not found or is not an armature.")

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="POSE")

    root_pb = obj.pose.bones.get(ROOT_BONE_NAME)
    hips_pb = obj.pose.bones.get(HIPS_BONE_NAME)

    if root_pb is None:
        raise ValueError(f"Bone '{ROOT_BONE_NAME}' not found in '{ARMATURE_NAME}'.")
    if hips_pb is None:
        raise ValueError(f"Bone '{HIPS_BONE_NAME}' not found in '{ARMATURE_NAME}'.")

    # ── Determine frame range from action keyframes ──────────────────────────
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

    obj_mat_inv = obj.matrix_world.inverted()

    # ── Pass 1: Sample world-space matrices for every frame ──────────────────
    print(f"[1/3] Sampling world matrices for {len(frames)} frames…")

    hips_world_per_frame: dict[int, mathutils.Matrix] = {}
    root_world_per_frame: dict[int, mathutils.Matrix] = {}

    for f in frames:
        scene.frame_set(f)
        hips_world_per_frame[f] = (obj.matrix_world @ hips_pb.matrix).copy()
        root_world_per_frame[f] = (obj.matrix_world @ root_pb.matrix).copy()

    # ── Additive baseline: Euler angles at the first frame ────────────────────
    # Sampled after Pass 1 so we never disturb the raw matrix data.
    if ADDITIVE_MODE:
        _, h0_rot_q, _ = hips_world_per_frame[frame_start].decompose()
        _, r0_rot_q, _ = root_world_per_frame[frame_start].decompose()
        h0_euler = h0_rot_q.to_euler("XYZ")  # hips rest rotation on frame 0
        r0_euler = r0_rot_q.to_euler("XYZ")  # root rest rotation on frame 0

    # ── Pass 2: Remove stale rotation FCurves for both bones ─────────────────
    print("[2/3] Clearing old rotation keyframes for Root and Hips…")

    if anim_data and anim_data.action:
        action      = anim_data.action
        root_prefix = f'pose.bones["{ROOT_BONE_NAME}"]'
        hips_prefix = f'pose.bones["{HIPS_BONE_NAME}"]'
        rot_tokens  = ("rotation_euler", "rotation_quaternion", "rotation_axis_angle")
        stale = [
            fc for fc in action.fcurves
            if (root_prefix in fc.data_path or hips_prefix in fc.data_path)
            and any(tok in fc.data_path for tok in rot_tokens)
        ]
        for fc in stale:
            action.fcurves.remove(fc)
        print(f"    Removed {len(stale)} stale rotation FCurve(s).")
    else:
        print("    No active action found on armature — rotation keyframes will be created fresh.")

    # ── Pass 3: Apply & keyframe the new transforms ──────────────────────────
    print("[3/3] Applying root rotation and inserting keyframes…")

    progress_step = max(1, len(frames) // 10)

    for i, f in enumerate(frames):
        scene.frame_set(f)

        h_world = hips_world_per_frame[f]
        r_world = root_world_per_frame[f]

        # ── Step A: Build new root world matrix with blended rotation ────────
        # Decompose both world matrices into (location, rotation, scale).
        r_loc, r_rot_q, r_scale = r_world.decompose()
        h_loc, h_rot_q, h_scale = h_world.decompose()

        # Work in Euler XYZ to allow per-axis selection without quaternion
        # interpolation issues (locomotion angles stay well within ±180°).
        r_euler = r_rot_q.to_euler("XYZ")
        h_euler = h_rot_q.to_euler("XYZ")

        new_root_euler = r_euler.copy()
        if ADDITIVE_MODE:
            # Delta = how much hips rotated since frame 0; add onto root's frame-0 rest.
            if EXTRACT_ROT_X:
                new_root_euler.x = r0_euler.x + (h_euler.x - h0_euler.x)
            if EXTRACT_ROT_Y:
                new_root_euler.y = r0_euler.y + (h_euler.y - h0_euler.y)
            if EXTRACT_ROT_Z:
                new_root_euler.z = r0_euler.z + (h_euler.z - h0_euler.z)
        else:
            if EXTRACT_ROT_X:
                new_root_euler.x = h_euler.x
            if EXTRACT_ROT_Y:
                new_root_euler.y = h_euler.y
            if EXTRACT_ROT_Z:
                new_root_euler.z = h_euler.z

        new_r_world = mathutils.Matrix.LocRotScale(r_loc, new_root_euler.to_quaternion(), r_scale)

        # Assign to root (armature-local space).
        root_pb.matrix = obj_mat_inv @ new_r_world

        # Propagate so child bones (including Hips) see the updated Root rotation.
        bpy.context.view_layer.update()

        # ── Step B: Restore hips to its original world matrix ────────────────
        # Root's rotation changed, so Hips' world transform shifted. Putting
        # hips_pb.matrix back to the sampled value makes Blender compute the
        # correct local offset — the body stays visually identical.
        hips_pb.matrix = obj_mat_inv @ h_world

        bpy.context.view_layer.update()

        # ── Step B2: Explicit rotation removal on hips (belt-and-suspenders) ─
        # The matrix assignment above already zeroes the extracted axes
        # mathematically. This block makes it explicit for Euler bones to
        # guard against any float-precision drift.
        #
        # Regular mode: root carries the full hips rotation → hips local on
        #   extracted axes should be exactly 0.
        # Additive mode: root carries rest+delta → hips local on extracted
        #   axes becomes the constant rest-pose offset (h0 - r0), which IS
        #   the correct inherited value. No extra zeroing needed; the matrix
        #   math gives the right answer.
        if not ADDITIVE_MODE and hips_pb.rotation_mode not in ("QUATERNION", "AXIS_ANGLE"):
            if EXTRACT_ROT_X:
                hips_pb.rotation_euler.x = 0.0
            if EXTRACT_ROT_Y:
                hips_pb.rotation_euler.y = 0.0
            if EXTRACT_ROT_Z:
                hips_pb.rotation_euler.z = 0.0
            bpy.context.view_layer.update()

        # ── Step C: Insert rotation keyframes ────────────────────────────────
        root_dp = _rotation_data_path(root_pb)
        hips_dp = _rotation_data_path(hips_pb)

        root_pb.keyframe_insert(data_path=root_dp, frame=f)
        hips_pb.keyframe_insert(data_path=hips_dp, frame=f)

        if i % progress_step == 0:
            pct = int(100 * i / len(frames))
            print(f"    {pct:3d}%  (frame {f})")

    scene.frame_set(frame_start)

    axes = "".join([
        "X(pitch) " if EXTRACT_ROT_X else "",
        "Y(roll) "  if EXTRACT_ROT_Y else "",
        "Z(yaw) "   if EXTRACT_ROT_Z else "",
    ]).strip() or "none"

    print(
        f"\nDone! Root rotation extracted across {len(frames)} frames "
        f"({frame_start}–{frame_end}).\n"
        f"  Root  → now carries world rotation axes: {axes}.\n"
        f"  Hips  → local rotation zeroed out on those axes."
    )


# ── Entry point ──────────────────────────────────────────────────────────────
extract_root_rotation()
