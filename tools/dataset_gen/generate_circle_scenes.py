"""
Generate a batch of "cubes converging on a circle" scene JSONs for Rigid IPC.

Each scene places a randomized number of cubes within a fixed viewing
radius (cubes are never placed further out than this, regardless of count),
each moving inward toward the origin at a randomized speed. Gravity is
zeroed so the only motion is the inward collision.

As cube count increases, cube size shrinks (with some random per-cube
variation) so that all cubes still fit within the fixed viewing radius
without any initial overlap — rather than pushing cubes further out to make
room, which would carry them out of camera view.

Usage:
    python3 generate_circle_scenes.py \
        --output-dir fixtures/3D/custom/generated \
        --num-scenes 20 \
        --min-cubes 2 --max-cubes 5 \
        [--min-speed 1.5] [--max-speed 4.0] \
        [--min-radius 2.5] [--max-radius 4.0] \
        [--seed 0]
"""
import argparse
import json
import math
import os
import random


BASE_CUBE_SCALE = 0.4  # cube scale used at low cube counts (reference size)
MIN_CUBE_SCALE = 0.05  # never shrink cubes below this, however many there are
TIMESTEP = 0.01
# Cap how far a cube can travel in one timestep, as a fraction of its own
# size, to avoid tunneling through the barrier before it can react. A
# fraction well under 1.0 leaves margin for the barrier to actually engage;
# raising this trades some of that margin for faster-looking motion.
MAX_TRAVEL_FRACTION_PER_STEP = 0.5
# Fraction of the theoretical max packing density to target when deriving a
# base cube size from cube count; well under 1.0 leaves room for the random
# per-cube placement (which isn't a perfect packing) to still succeed.
PACKING_DENSITY_TARGET = 0.12
# Per-cube scale is sampled as base_scale * uniform(SCALE_JITTER_LOW, SCALE_JITTER_HIGH).
SCALE_JITTER_LOW = 0.8
SCALE_JITTER_HIGH = 1.2


def derive_base_scale(num_cubes, max_radius):
    """Pick a reference cube scale so that num_cubes cubes can plausibly fit
    within a disk of radius max_radius without overlapping, at a packing
    density well short of the theoretical maximum (since placement here is
    randomized, not a perfect packing).

    At low cube counts the area-based formula would suggest cubes larger
    than BASE_CUBE_SCALE (plenty of room for a few cubes); cap there so
    scenes with few cubes keep a consistent, familiar cube size instead of
    ballooning. At higher counts the formula's value drops below
    BASE_CUBE_SCALE on its own, which is the shrinking behavior we want —
    only a floor at MIN_CUBE_SCALE prevents cubes from disappearing
    entirely at extreme counts."""
    view_area = math.pi * max_radius ** 2
    area_per_cube = (view_area * PACKING_DENSITY_TARGET) / num_cubes
    # A cube's own footprint (viewed from above) is scale^2.
    scale = math.sqrt(area_per_cube)
    return min(BASE_CUBE_SCALE, max(MIN_CUBE_SCALE, scale))


def make_bodies(num_cubes, min_speed, max_speed, min_radius, max_radius, rng):
    bodies = []
    base_angle_step = 2 * math.pi / num_cubes
    base_scale = derive_base_scale(num_cubes, max_radius)

    # max_radius is a fixed camera-view bound: cubes are never placed
    # further out than this, however many cubes there are. Instead, cube
    # size (derived above) shrinks as cube count grows to make room.
    effective_min_radius = min(min_radius, max_radius)
    effective_max_radius = max_radius

    min_gap_fraction = 0.1  # required clearance between cube surfaces,
                             # as a fraction of the smaller cube's scale
    max_attempts_per_cube = 200

    placed = []  # (pos_x, pos_z, half_extent) of already-placed cubes

    for i in range(num_cubes):
        base_angle = i * base_angle_step
        cube_scale = base_scale * rng.uniform(SCALE_JITTER_LOW, SCALE_JITTER_HIGH)
        cube_scale = max(MIN_CUBE_SCALE, cube_scale)
        half_extent = cube_scale / 2.0

        found = False
        for _attempt in range(max_attempts_per_cube):
            angle = base_angle + rng.uniform(-0.15, 0.15)
            radius = rng.uniform(effective_min_radius, effective_max_radius)
            pos_x = radius * math.cos(angle)
            pos_z = radius * math.sin(angle)

            # Axis-aligned bounding boxes (cubes are never rotated here)
            # overlap iff they overlap on both axes simultaneously; require
            # clearance on at least one axis to guarantee no overlap. Each
            # pair's required separation depends on both cubes' own sizes,
            # since sizes can differ.
            collides = False
            for other_x, other_z, other_half in placed:
                min_gap = min_gap_fraction * min(cube_scale, other_half * 2)
                min_center_dist = half_extent + other_half + min_gap
                if abs(pos_x - other_x) < min_center_dist and abs(pos_z - other_z) < min_center_dist:
                    collides = True
                    break

            if not collides:
                found = True
                break

        if not found:
            raise RuntimeError(
                f"Could not place cube {i}/{num_cubes} (scale={cube_scale:.4f}) "
                f"without initial overlap within the fixed viewing radius "
                f"({max_radius}); try fewer cubes, a larger --max-radius, or "
                f"a lower PACKING_DENSITY_TARGET."
            )

        placed.append((pos_x, pos_z, half_extent))

        # Cap speed so no cube can cross more than
        # MAX_TRAVEL_FRACTION_PER_STEP of its own size in a single timestep.
        # Smaller cubes therefore get a proportionally lower speed cap,
        # keeping the same tunneling-safety margin regardless of cube size.
        max_safe_speed = (cube_scale * MAX_TRAVEL_FRACTION_PER_STEP) / TIMESTEP
        effective_max_speed = min(max_speed, max_safe_speed)
        effective_min_speed = min(min_speed, effective_max_speed)
        speed = rng.uniform(effective_min_speed, effective_max_speed)
        vel_x = -speed * math.cos(angle)
        vel_z = -speed * math.sin(angle)

        bodies.append({
            "mesh": "cube.obj",
            "position": [pos_x, 0, pos_z],
            "rotation": [0, 0, 0],
            "scale": [cube_scale, cube_scale, cube_scale],
            "linear_velocity": [vel_x, 0, vel_z],
            "is_dof_fixed": [False, False, False, False, False, False]
        })

    return bodies


def make_scene(bodies, solve_collisions):
    return {
        "scene_type": "distance_barrier_rb_problem",
        "solver": "ipc_solver",
        "timestep": TIMESTEP,
        "max_time": 2,
        "solve_collisions": solve_collisions,
        "distance_barrier_constraint": {
            "initial_barrier_activation_distance": 1e-4
        },
        "rigid_body_problem": {
            "coefficient_restitution": -1,
            "gravity": [0, 0, 0],
            "do_intersection_check": True,
            "rigid_bodies": bodies
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--num-scenes", type=int, default=20)
    parser.add_argument("--min-cubes", type=int, default=2)
    parser.add_argument("--max-cubes", type=int, default=5)
    parser.add_argument("--min-speed", type=float, default=3.0)
    parser.add_argument("--max-speed", type=float, default=8.0)
    parser.add_argument("--min-radius", type=float, default=2.5)
    parser.add_argument("--max-radius", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--single-index",
        type=int,
        default=None,
        help="If set, generate only this one scene, named with this index, "
             "using --scene-seed for its randomness (independent of --seed).",
    )
    parser.add_argument(
        "--scene-seed",
        type=int,
        default=None,
        help="Seed for the single scene when --single-index is set. Pass a "
             "new value to get a different random configuration on retry.",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    if args.single_index is not None:
        indices_and_rngs = [(args.single_index, random.Random(args.scene_seed))]
    else:
        base_rng = random.Random(args.seed)
        indices_and_rngs = [(i, base_rng) for i in range(args.num_scenes)]

    written = []
    for i, rng in indices_and_rngs:
        num_cubes = rng.randint(args.min_cubes, args.max_cubes)
        bodies = make_bodies(
            num_cubes=num_cubes,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            min_radius=args.min_radius,
            max_radius=args.max_radius,
            rng=rng,
        )

        for solve_collisions, suffix in [(True, "collisions_on"), (False, "collisions_off")]:
            scene = make_scene(bodies, solve_collisions)
            name = f"circle_cubes_{i:03d}_n{num_cubes}_{suffix}.json"
            out_path = os.path.join(args.output_dir, name)
            with open(out_path, "w") as f:
                json.dump(scene, f, indent=4)
            written.append(out_path)

    print(f"[generate_circle_scenes] Wrote {len(written)} scenes to {args.output_dir}")


if __name__ == "__main__":
    main()