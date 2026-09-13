import argparse
import json
import os
import shutil
import subprocess
import sys


def run(cmd, log_path, cwd=None):
    """Run cmd, sending all its stdout/stderr to log_path instead of the
    terminal. Raises with the log path on failure so the person can inspect
    what went wrong without scrolling a wall of solver output."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w") as log_file:
        result = subprocess.run(cmd, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(cmd)}\n"
            f"See log: {log_path}"
        )
    return result


def validate_scene_json(scene_path):
    with open(scene_path) as f:
        scene = json.load(f)
    rbp = scene.get("rigid_body_problem", {})
    if not rbp.get("do_intersection_check", False):
        print(f"[warning] do_intersection_check disabled: {scene_path}")
    return scene


def run_simulation(sim_binary, scene_path, sim_out_dir, num_steps, log_path):
    os.makedirs(sim_out_dir, exist_ok=True)
    cmd = [
        sim_binary,
        "--ngui",
        "--scene-path", scene_path,
        "--output-path", sim_out_dir,
        "--num-steps", str(num_steps),
        "--log", "off",
    ]
    run(cmd, log_path)


def run_blender_render(blender_path, blender_script, sim_out_dir, render_config_path, variant_out_dir, log_path):
    os.makedirs(variant_out_dir, exist_ok=True)
    cmd = [
        blender_path, "-b", "--python", blender_script, "--",
        sim_out_dir, render_config_path, variant_out_dir,
    ]
    run(cmd, log_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--render-config", required=True, nargs="+")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--sim-binary", default="rigid_ipc_sim")
    parser.add_argument("--blender", default="blender")
    parser.add_argument(
        "--blender-script",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_render.py"),
    )
    parser.add_argument("--num-steps", type=int, default=200)
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="If a previous run already completed successfully for this --name, "
             "skip it instead of erroring. Completion is tracked via a marker "
             "file, not just directory existence, so interrupted/partial runs "
             "are still redone.",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Delete any existing output dir for this --name before running, "
             "regardless of whether it was previously completed.",
    )
    args = parser.parse_args()

    scene_path = args.scene
    validate_scene_json(scene_path)

    example_out_dir = os.path.join(args.dataset_root, args.name)
    done_marker = os.path.join(example_out_dir, ".done")

    if os.path.exists(example_out_dir):
        if args.overwrite:
            shutil.rmtree(example_out_dir)
        elif os.path.exists(done_marker):
            if args.skip_existing:
                print(f"[skip] {args.name}")
                return
            raise RuntimeError(
                f"Output directory already completed, refusing to overwrite: {example_out_dir} "
                f"(pass --overwrite to redo it, or --skip-existing to skip it in a batch)"
            )
        else:
            # Directory exists but has no .done marker: leftover from a prior
            # crashed/interrupted run. Never resume a partial run in place;
            # wipe it and start clean, since intermediate sim/render files
            # can't be trusted to be complete or consistent.
            shutil.rmtree(example_out_dir)

    os.makedirs(example_out_dir)
    logs_dir = os.path.join(example_out_dir, "logs")

    sim_out_dir = os.path.join(example_out_dir, "sim")
    sim_log_path = os.path.join(logs_dir, "sim.log")
    run_simulation(args.sim_binary, scene_path, sim_out_dir, args.num_steps, sim_log_path)
    print(f"[sim done] {args.name}")

    for render_config_path in args.render_config:
        variant_name = os.path.splitext(os.path.basename(render_config_path))[0]
        variant_out_dir = os.path.join(example_out_dir, variant_name)
        render_log_path = os.path.join(logs_dir, f"render_{variant_name}.log")
        run_blender_render(
            args.blender, args.blender_script, sim_out_dir, render_config_path,
            variant_out_dir, render_log_path
        )
        print(f"[render done] {args.name} ({variant_name})")

    shutil.copy(scene_path, example_out_dir)
    for render_config_path in args.render_config:
        shutil.copy(render_config_path, example_out_dir)

    # Write the completion marker last, after everything else succeeded, so
    # its presence reliably means "this example is fully usable".
    with open(done_marker, "w") as f:
        f.write("")
    print(f"[complete] {args.name}")


if __name__ == "__main__":
    main()