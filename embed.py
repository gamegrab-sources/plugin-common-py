#!/usr/bin/env python3
"""Writes a plugin's shipped plugin.py: its source with `gamegrab.py` embedded.

    embed.py <plugin source> <gamegrab.py> <output>

droidtop runs a python-kind plugin from one file (docs/plugin-api.md 1.3), so the
shared module cannot sit beside it. The plugin's source imports it with exactly
this line, which is replaced:

    import gamegrab as gg  # embedded by build.sh

by the module's text executed into a fresh module object named `gamegrab`. Nothing
is put in sys.modules, so two plugins carrying different versions of this file
never meet, even in one interpreter.
"""
import sys

MARKER = "import gamegrab as gg  # embedded by build.sh"


def embed(plugin_source, gamegrab_source):
    lines = plugin_source.split("\n")
    hits = [i for i, line in enumerate(lines) if line.strip() == MARKER]
    if len(hits) != 1:
        raise SystemExit("the plugin source must contain the line %r exactly once" % MARKER)
    block = "\n".join(
        [
            "# gamegrab (gamegrab-sources/plugin-common-py), embedded by build.sh: see embed.py there.",
            "import types as _gamegrab_types",
            "_GAMEGRAB_SOURCE = %r" % gamegrab_source,
            "gg = _gamegrab_types.ModuleType(\"gamegrab\")",
            "exec(compile(_GAMEGRAB_SOURCE, \"gamegrab.py\", \"exec\"), gg.__dict__)",
            "del _GAMEGRAB_SOURCE",
        ]
    )
    lines[hits[0]] = block
    return "\n".join(lines)


def main(argv):
    if len(argv) != 4:
        raise SystemExit(__doc__)
    with open(argv[1], encoding="utf-8") as f:
        plugin = f.read()
    with open(argv[2], encoding="utf-8") as f:
        common = f.read()
    out = embed(plugin, common)
    compile(out, "plugin.py", "exec")
    with open(argv[3], "w", encoding="utf-8") as f:
        f.write(out)


if __name__ == "__main__":
    main(sys.argv)
