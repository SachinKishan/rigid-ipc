#!/usr/bin/env bash
# Generate a batch of circle-cube scenes and immediately run the full
# sim + render pipeline on each one.
#
# Usage (run from anywhere; paths resolve relative to this script):
#   ./run_circle_batch.sh <dataset-root> [num-scenes] [min-cubes] [max-cubes]
#
# Example:
#   ./run_circle_batch.sh /tmp/dataset_results1 20 2 5
#
# Set OVERWRITE=1 to wipe <dataset-root> entirely before running, for a full
# clean rebuild instead of skipping scenes that already completed:
#   OVERWRITE=1 ./run_circle_batch.sh /tmp/dataset_results1 20 2 5

# Note: no `set -e` at the top level. A single scene failing (sim crash on a
# degenerate config, Blender hiccup, etc.) should not kill the whole batch —
# we want to record it and keep going. Individual commands that must succeed
# (scene generation itself) are checked explicitly instead.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DATASET_ROOT="${1:-/tmp/dataset_results1}"
NUM_SCENES="${2:-20}"
MIN_CUBES="${3:-2}"
MAX_CUBES="${4:-5}"
OVERWRITE="${OVERWRITE:-0}"

SCENE_DIR="$REPO_ROOT/fixtures/3D/custom/generated"
RENDER_CONFIG="$SCRIPT_DIR/render_configs/render_config.json"
SIM_BINARY="$REPO_ROOT/cmake-build-release/rigid_ipc_sim"
BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"

if [ "$OVERWRITE" = "1" ] && [ -d "$DATASET_ROOT" ]; then
    rm -rf "$DATASET_ROOT"
fi

mkdir -p "$DATASET_ROOT"
FAIL_LOG="$DATASET_ROOT/failures.log"
MANIFEST="$DATASET_ROOT/manifest.csv"
: > "$FAIL_LOG"
if [ ! -f "$MANIFEST" ]; then
    echo "name,status" > "$MANIFEST"
fi

rm -rf "$SCENE_DIR"
mkdir -p "$SCENE_DIR"

python3 "$SCRIPT_DIR/generate_circle_scenes.py" \
    --output-dir "$SCENE_DIR" \
    --num-scenes "$NUM_SCENES" \
    --min-cubes "$MIN_CUBES" \
    --max-cubes "$MAX_CUBES"
if [ $? -ne 0 ]; then
    echo "[run_circle_batch] Scene generation failed, aborting." >&2
    exit 1
fi

total_files=$(ls "$SCENE_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
echo "[run_circle_batch] Running $total_files scenes into $DATASET_ROOT"
i=0
succeeded=0
failed=0
if [ "$OVERWRITE" = "1" ]; then
    EXAMPLE_FLAG="--overwrite"
else
    EXAMPLE_FLAG="--skip-existing"
fi
for f in "$SCENE_DIR"/*.json; do
    name=$(basename "$f" .json)
    i=$((i + 1))
    echo "[$i/$total_files] $name"
    if python3 "$SCRIPT_DIR/generate_example.py" \
        --scene "$f" \
        --render-config "$RENDER_CONFIG" \
        --dataset-root "$DATASET_ROOT" \
        --name "$name" \
        --sim-binary "$SIM_BINARY" \
        --blender "$BLENDER" \
        $EXAMPLE_FLAG; then
        succeeded=$((succeeded + 1))
        echo "$name,ok" >> "$MANIFEST"
    else
        failed=$((failed + 1))
        echo "[run_circle_batch] FAILED: $name (see $FAIL_LOG)" >&2
        echo "$name" >> "$FAIL_LOG"
        echo "$name,failed" >> "$MANIFEST"
    fi
done

echo "[run_circle_batch] Done. $succeeded/$total_files succeeded, $failed failed."
if [ "$failed" -gt 0 ]; then
    echo "[run_circle_batch] Failed scene names logged in $FAIL_LOG"
fi