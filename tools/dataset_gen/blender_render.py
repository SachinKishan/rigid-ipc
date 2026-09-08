"""
Blender headless render script.
Run as: blender -b --python blender_render.py -- <sim_dir> <render_config.json> <out_dir>

<sim_dir>          directory containing sim.json and sim.glb (output of rigid_ipc_sim)
<render_config.json>  camera/light/body_colors/shading config
<out_dir>          where to write frames/, labels.csv, video.mp4
"""
import bpy
import json
import os
import csv
import sys


def parse_args():
    # Blender passes its own args before "--"; ours come after.
    argv = sys.argv
    if "--" not in argv:
        raise RuntimeError("Expected '--' separator before script args")
    idx = argv.index("--")
    script_args = argv[idx + 1:]
    if len(script_args) != 3:
        raise RuntimeError(
            f"Expected 3 args (sim_dir, render_config, out_dir), got {script_args}"
        )
    return script_args


def hex_to_rgba(hex_color):
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b, 1.0)


def main():
    sim_dir, render_config_path, out_dir = parse_args()

    sim_json_path = os.path.join(sim_dir, "sim.json")
    glb_path = os.path.join(sim_dir, "sim.glb")
    frames_dir = os.path.join(out_dir, "frames")
    video_path = os.path.join(out_dir, "video.mp4")
    csv_path = os.path.join(out_dir, "labels.csv")

    os.makedirs(frames_dir, exist_ok=True)

    with open(render_config_path) as f:
        render_cfg = json.load(f)

    with open(sim_json_path) as f:
        sim_data = json.load(f)

    labels = sim_data["stats"]["step_has_intersections"]
    num_steps = len(labels)
    print(f"[blender_render] Loaded {num_steps} per-step labels")

    timestep = sim_data["args"]["timestep"]
    fps = render_cfg.get("fps_override") or int(round(1 / timestep))

    # ---- Write labels.csv ----
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "label"])
        for i, is_intersecting in enumerate(labels):
            writer.writerow([i + 1, "INTERSECT" if is_intersecting else "OK"])
    print(f"[blender_render] Wrote {csv_path}")

    # ---- Set up scene. fps MUST be set before import (see notes). ----
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = fps

    bpy.ops.import_scene.gltf(filepath=glb_path)

    scene.frame_start = 1
    scene.frame_end = num_steps

    # ---- Camera ----
    cam_cfg = render_cfg.get("camera", {"location": [0, -10, 3], "rotation": [1.3, 0, 0]})
    bpy.ops.object.camera_add(
        location=cam_cfg["location"], rotation=cam_cfg["rotation"]
    )
    camera = bpy.context.active_object
    scene.camera = camera

    # ---- Light ----
    light_cfg = render_cfg.get(
        "light",
        {"type": "SUN", "location": [0, 0, 5], "rotation": [0.7853, 0, 0.7853], "energy": 3},
    )
    bpy.ops.object.light_add(type=light_cfg["type"], location=light_cfg["location"])
    light = bpy.context.active_object
    light.rotation_euler = light_cfg["rotation"]
    light.data.energy = light_cfg["energy"]

    # ---- Per-body colors + shading ----
    # Mesh objects are named after their source .obj files by the glTF importer,
    # in the order they appear in the scene JSON's "rigid_bodies" list, with
    # Blender's standard ".001", ".002" suffixes for name collisions.
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    body_colors = render_cfg.get("body_colors", [])
    shading = render_cfg.get("shading", "flat")

    for i, obj in enumerate(mesh_objects):
        if i < len(body_colors):
            mat = bpy.data.materials.new(name=f"body_{i}_mat")
            mat.diffuse_color = hex_to_rgba(body_colors[i])
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf is not None:
                bsdf.inputs["Base Color"].default_value = hex_to_rgba(body_colors[i])
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

        if shading == "flat":
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_flat()
        elif shading == "smooth":
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_smooth()

    # ---- Render engine ----
    scene.render.engine = "BLENDER_EEVEE"
    resolution = render_cfg.get("resolution", [1280, 720])
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]

    background_color = render_cfg.get("background_color")
    if background_color:
        world = bpy.data.worlds.new("World")
        scene.world = world
        world.use_nodes = True
        bg_node = world.node_tree.nodes.get("Background")
        if bg_node is not None:
            bg_node.inputs["Color"].default_value = hex_to_rgba(background_color)

    # ---- Render labeled PNG frames ----
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    for frame in range(1, num_steps + 1):
        scene.frame_set(frame)
        label = "INTERSECT" if labels[frame - 1] else "OK"
        scene.render.filepath = os.path.join(frames_dir, f"frame_{frame:04d}_{label}.png")
        bpy.ops.render.render(write_still=True)
    print(f"[blender_render] Rendered {num_steps} labeled PNG frames to {frames_dir}")

    # ---- Render full video ----
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = video_path
    bpy.ops.render.render(animation=True)
    print(f"[blender_render] Rendered video to {video_path}")


if __name__ == "__main__":
    main()
