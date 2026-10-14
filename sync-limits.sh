#!/bin/sh
# Refreshes plugin-view-limits.json from droidtop, its one source
# (Droidtop/droidtop docs/view-limits/plugin-view-limits.json). Run it when
# droidtop's limits change; never edit the copy by hand.
set -eu
ref="${1:-main}"
cd "$(dirname "$0")"
curl -fsSL "https://raw.githubusercontent.com/Droidtop/droidtop/$ref/docs/view-limits/plugin-view-limits.json" -o plugin-view-limits.json.new
python3 -c 'import json,sys; json.load(open("plugin-view-limits.json.new"))'
mv plugin-view-limits.json.new plugin-view-limits.json
