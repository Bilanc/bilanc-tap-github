#!/usr/bin/env bash
set -euo pipefail

# should be ran from root of tap

CONFIG_PATH="${CONFIG_PATH:-config.json}"
VENV_DIR="${VENV_DIR:-.venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  python3.10 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e .

# Discover always outputs the full catalog, so we filter it down to the copilot stream,
# mark it as selected, and write it to properties.json.
python tap_github/__init__.py --config "$CONFIG_PATH" --discover | python -c '
import json
import sys

catalog = json.load(sys.stdin)
target_stream = "copilot_user_metrics_28_day"

streams = []
for stream in catalog.get("streams", []):
    if stream.get("tap_stream_id") != target_stream:
        continue

    # Mark the stream as selected at the schema root.
    schema = stream.get("schema", {})
    schema["selected"] = True
    stream["schema"] = schema
    streams.append(stream)

# Emit a minimal catalog containing only the selected Copilot stream.
json.dump({"streams": streams}, sys.stdout, indent=2)
' > properties.json

# Run the tap using the filtered catalog.
python tap_github/__init__.py --config "$CONFIG_PATH" --properties properties.json
