# plugin-common-py

What the gamegrab-sources Python plugins for
[droidtop](https://github.com/Droidtop/droidtop) share. Unofficial: not part of
droidtop.

- `gamegrab.py`: the shared module. Host calls through droidtop's broker
  (`net.http`, `net.download`, `web.session`, the data API, notifications), per-site
  request pacing, a cache that falls back to a stale copy when a site is down, view
  documents and replies (droidtop docs/plugin-api.md 1.3 and 1.6), the plugin's
  entry points (`handle`, `start_job`, `cancel_job`), lenient RSS reading, magnet
  links, and XenForo forum parsing (thread titles, prefixes, listings, the first
  post; ported from droidtop-plugin-f95).
- `embed.py`: droidtop runs a python-kind plugin from one file, `plugin.py`. A
  plugin's source imports this module with the line
  `import gamegrab as gg  # embedded by build.sh`, and its build.sh runs
  `embed.py` to replace that line with this module's text, executed into a fresh
  module object (nothing goes into `sys.modules`).
- `testing.py`: a fake droidtop host for the plugins' tests. Not shipped.

Plugins keep this repository as the git submodule `common`, pinned to a commit;
a plugin picks up a change here by moving its submodule and bumping its own
version.

Tests: `python3 test_gamegrab.py`.

## Handing links to other apps

droidtop has no torrent client and, as of this version, no host call that opens a
link in another app. `hand_off` asks for `apps.view {uri, chooser, title}`
(requested from droidtop) and the plugins show the link to copy while droidtop
refuses it.

## Licence

GPL-3.0, see LICENSE.
