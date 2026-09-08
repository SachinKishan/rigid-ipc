"""
Generate one labeled dataset example from a Rigid IPC scene JSON.

Usage:
    python3 generate_example.py \
        --scene <scene.json> \
        --render-config <render_config.json> \
        --dataset-root <path/to/dataset> \
        --name <example_name> \
        [--sim-binary <path/to/rigid_ipc_sim>] \
        [--blender <path/to/blender>] \
        [--num-steps N]

Produces, under <dataset-root>/<example_name>/:
    video.mp4
    labels.csv
    frames/frame_XXXX_LABEL.png
    scene.json          (copy of the input scene, for provenance)
    render_config.json  (copy of the input render config, for provenance)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile


def run(cmd, **kwargs):
    print(f"[generate_example] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")
    return result


def validate_scene_json(scene_path):
    with open(scene_path) as f:
        scene = json.load(f)
    rb_problem = scene.get("rigid_body_problem", {})
    if "solve_collisions" not in scene:
        print(
            "[generate_example] WARNING: scene JSON has no top-level "
            "'solve_collisions' key; simulator will default to True."
        )
    if not rb_problem.get("do_intersection_check", False):
        print(
            "[generate_example] WARNING: 'do_intersection_check' is not true "
            "in rigid_body_problem; per-frame intersection labels will all "
            "be False. This is almost certainly not what you want."
        )
    return scene


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True, help="Path to Rigid IPC scene JSON")
    parser.add_argument(
        "--render-config", required=True, nargs="+",
        help="One or more paths to render config JSON files. Each produces a "
             "separate rendered variant (e.g. colorful, same_color) from the "
             "same simulation.",
    )
    parser.add_argument("--dataset-root", required=True, help="Root dataset directory")
    parser.add_argument("--name", required=True, help="Name for this example (subfolder)")
    parser.add_argument(
        "--sim-binary",
        default="rigid_ipc_sim",
        help="Path to the rigid_ipc_sim executable",
    )
    parser.add_argument(
        "--blender",
        default="blender",
        help="Path to the blender executable",
    )
    parser.add_argument(
        "--blender-script",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_render.py"),
        help="Path to the blender_render.py script",
    )
    parser.add_argument("--num-steps", type=int, default=200, help="Max simulation steps")
    args = parser.parse_args()

    scene_path = os.path.abspath(args.scene)
    render_config_paths = [os.path.abspath(p) for p in args.render_config]
    dataset_root = os.path.abspath(args.dataset_root)

    validate_scene_json(scene_path)

    example_out_dir = os.path.join(dataset_root, args.name)
    if os.path.exists(example_out_dir):
        raise RuntimeError(
            f"Output directory already exists, refusing to overwrite: {example_out_dir}"
        )
    os.makedirs(example_out_dir)

    with tempfile.TemporaryDirectory() as sim_tmp_dir:
    # ---- Step 1: run the simulator headlessly (once, shared across variants) ----
        run(
            [
                args.sim_binary,
                "--ngui",
                "--scene-path", scene_path,
                "--output-path", sim_tmp_dir,
                "--num-steps", str(args.num_steps),
            ]
        )

        sim_json_path = os.path.join(sim_tmp_dir, "sim.json")
        sim_glb_path = os.path.join(sim_tmp_dir, "sim.glb")
        if not os.path.exists(sim_json_path) or not os.path.exists(sim_glb_path):
            raise RuntimeError(
                f"Simulation did not produce expected outputs in {sim_tmp_dir}"
            )

        # ---- Step 2: render via Blender headlessly, once per render config ----
        for render_config_path in render_config_paths:
            variant_name = os.path.splitext(os.path.basename(render_config_path))[0]
            variant_out_dir = os.path.join(example_out_dir, variant_name)
            os.makedirs(variant_out_dir, exist_ok=True)

            run(
                [
                    args.blender,
                    "-b",
                    "--python", args.blender_script,
                    "--",
                    sim_tmp_dir,
                    render_config_path,
                    variant_out_dir,
                ]
            )

            shutil.copy(render_config_path, os.path.join(variant_out_dir, "render_config.json"))

        # ---- Step 3: copy the scene once at the top level for provenance ----
        shutil.copy(scene_path, os.path.join(example_out_dir, "scene.json"))
        print(f"[generate_example] Done. Output at: {example_out_dir}")


if __name__ == "__main__":
    main()
