"""Tests for gamegrab.py (python3 test_gamegrab.py). The pages below are small hand-written
samples in the markup the sites use, not copies of their pages."""
import json
import os
import unittest

import embed
import gamegrab as gg
from testing import FakeHost, install

STRUCT_ITEM = """
<div style="" class="structItem structItem--thread is-prefix14 is-prefix8 js-inlineModContainer js-threadListItem-18978" data-author="someone">
 <div class="structItem-cell structItem-cell--main" data-xf-init="touch-proxy">
  <div class="structItem-title"><a href="/forums/games.6/?prefix_id[0]=14" class="labelLink" rel="nofollow"><span class="label label--completed" dir="auto">Complete</span></a><span class="label-append">&nbsp;</span><a href="/forums/games.6/?prefix_id[0]=8" class="labelLink" rel="nofollow"><span class="label label--blue" dir="auto">Ren'Py</span></a> <a href="/threads/sample-game-v1-0-sample-dev.18978/" class="" data-tp-primary="on" data-xf-init="" rel="nofollow"> Sample Game [v1.0] [Sample Dev] </a> </div>
 </div>
</div>
"""

SEARCH_ROW = """
<li class="block-row block-row--separated  js-inlineModContainer" data-author="x">
 <div class="contentRow"><div class="contentRow-main">
  <h3 class="contentRow-title"><a href="/threads/another-one-ep-3-studio.2201/"><span class="label label--orange" dir="auto">Unity</span> Another One [Ep. 3] [Studio]</a></h3>
 </div></div>
</li>
"""

THREAD = """<html><head><title>Sample Game [v1.0] [Sample Dev] | Forum</title>
<link rel="canonical" href="https://lewdcorner.com/threads/sample-game-v1-0-sample-dev.18978/" /></head>
<body><html data-csrf="1700000000,abcdef">
<h1 class="p-title-value"><i class="fa--xf">icon</i><span class="label label--blue" dir="auto">Ren'Py</span><span class="label-append">&nbsp;</span>Sample Game [v1.0] [Sample Dev]</h1>
<article class="message message--post js-post" data-content="post-1"><div class="message-content">
<div class="bbWrapper">Overview text.<br /><b>DOWNLOAD</b><br />Win/Linux: <a href="https://mega.nz/file/abc" class="link link--external">MEGA</a> - <a href="https://pixeldrain.com/u/xyz" class="link link--external">PIXELDRAIN</a><br /><a href="https://lewdcorner.com/threads/other.5/" class="link link--internal">other</a></div>
<div class="js-selectToQuoteEnd">&nbsp;</div></div></article>
</body></html>"""

FEED = """<?xml version="1.0"?><rss><channel><title>t</title>
<item><title>2183- Game: Sub (v1.0.2 + MULTi10) [DODI Repack]</title><link>https://example.site/game-sub/</link>
<span class="x" data-raw=\\"1\\"></span>
<category><![CDATA[Uncategorized]]></category><description><![CDATA[Some <b>text</b>]]></description></item>
<item><title>Other &#8211; v2</title><link>https://example.site/other/</link></item>
</channel></rss>"""


class Titles(unittest.TestCase):
    def test_split(self):
        self.assertEqual(gg.split_title("Sample Game [v1.0] [Sample Dev]"), ("Sample Game", "v1.0", "Sample Dev"))
        self.assertEqual(gg.split_title("Another One [Ep. 3] [Studio]"), ("Another One", "Ep. 3", "Studio"))
        self.assertEqual(gg.split_title("Lone [Dev]"), ("Lone", None, "Dev"))
        self.assertEqual(gg.split_title("Plain"), ("Plain", None, None))

    def test_thread_id(self):
        self.assertEqual(gg.thread_id("https://lewdcorner.com/threads/sample-game.18978/", "lewdcorner.com"), 18978)
        self.assertEqual(gg.thread_id("lewdcorner.com/threads/18978", "lewdcorner.com"), 18978)
        self.assertEqual(gg.thread_id("18978", "lewdcorner.com"), 18978)
        self.assertIsNone(gg.thread_id("https://f95zone.to/threads/x.1/", "lewdcorner.com"))
        self.assertIsNone(gg.thread_id("0", "lewdcorner.com"))


class XenForo(unittest.TestCase):
    def test_list(self):
        rows = gg.thread_list(STRUCT_ITEM + SEARCH_ROW, "lewdcorner.com")
        self.assertEqual([r["id"] for r in rows], [18978, 2201])
        self.assertEqual(rows[0]["name"], "Sample Game")
        self.assertEqual(rows[0]["version"], "v1.0")
        self.assertEqual(rows[0]["developer"], "Sample Dev")
        self.assertEqual(rows[0]["labels"], ["Complete", "Ren'Py"])
        self.assertEqual(rows[1]["title"], "Another One [Ep. 3] [Studio]")
        self.assertEqual(rows[1]["labels"], ["Unity"])

    def test_thread(self):
        t = gg.thread_page(THREAD, "lewdcorner.com")
        self.assertEqual(t["title"], "Sample Game [v1.0] [Sample Dev]")
        self.assertEqual(t["version"], "v1.0")
        self.assertEqual(t["labels"], ["Ren'Py"])
        self.assertIn("mega.nz", t["first_post"])
        self.assertEqual(gg.csrf_token(THREAD), "1700000000,abcdef")
        self.assertEqual(gg.engine_of(t["labels"]), "renpy")
        self.assertEqual([h for h, _ in gg.links(t["first_post"])][:2], ["https://mega.nz/file/abc", "https://pixeldrain.com/u/xyz"])


class Feeds(unittest.TestCase):
    def test_lenient(self):
        items = gg.rss_items(FEED)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["categories"], ["Uncategorized"])
        self.assertEqual(items[1]["title"], "Other – v2")

    def test_magnet(self):
        m = gg.magnet("ABCDEF0123", "A b")
        self.assertTrue(m.startswith("magnet:?xt=urn:btih:ABCDEF0123&dn=A+b&tr=udp%3A%2F%2F"))
        self.assertEqual(gg.magnet_hash(m), "abcdef0123")


class Host(unittest.TestCase):
    def setUp(self):
        self.host = install(gg, FakeHost())

    def test_data_roundtrip_in_chunks(self):
        big = {"x": "y" * (300 * 1024)}
        gg.write_json("big.json", big)
        self.assertEqual(gg.read_json("big.json"), big)
        self.assertIsNone(gg.read_json("missing.json"))

    def test_truncated_page_is_downloaded(self):
        self.host.pages["https://example.site/big"] = "a" * (200 * 1024)
        page = gg.get_page("https://example.site/big", "scratch.html")
        self.assertEqual(len(page.body), 200 * 1024)
        self.assertNotIn("scratch.html", self.host.files)

    def test_cache_uses_stale_copy_when_site_fails(self):
        calls = []

        def produce():
            calls.append(1)
            if len(calls) > 1:
                raise gg.HostError("FAILED", "down")
            return [1, 2]

        self.assertEqual(gg.cached("k", 10, produce, now=100), [1, 2])
        self.assertEqual(gg.cached("k", 10, produce, now=105), [1, 2])
        self.assertEqual(len(calls), 1)
        self.assertEqual(gg.cached("k", 10, produce, now=200), [1, 2])
        self.assertEqual(len(calls), 2)

    def test_handoff(self):
        uri = "magnet:?xt=urn:btih:ab"
        self.assertEqual(gg.hand_off(uri, "x"), (True, None))
        self.assertEqual(self.host.calls[-1], ("apps", "view", {"uri": uri, "title": "x"}))
        self.host.handoff = "none"
        self.assertEqual(gg.hand_off(uri, "x"), (False, "no app opens magnet links."))
        page = json.loads(gg.handoff_result(uri, "x", "Opened")["values"]["view"])
        self.assertEqual(page["sections"][0]["items"][1]["value"], uri)
        self.host.handoff = "denied"
        self.assertEqual(gg.hand_off(uri, "x"), (False, gg.HANDOFF_DENIED))
        self.host.handoff = False
        self.assertEqual(gg.hand_off(uri, "x"), (False, gg.NO_HANDOFF))

    def test_split_sets(self):
        self.assertEqual(gg.split_part("Game_--_.part2.rar"), ("game_--_.rar", 2))
        self.assertEqual(gg.split_part("Game.7z.003"), ("game.7z", 3))
        self.assertIsNone(gg.split_part("Game.rar"))
        self.assertTrue(gg.is_split_set(["G.part2.rar", "G.part1.rar"]))
        self.assertFalse(gg.is_split_set(["G.part1.rar", "G.part3.rar"]))
        self.assertFalse(gg.is_split_set(["G.part1.rar", "H.part2.rar"]))
        many = gg.downloads_result("m", [{"url": "https://a/1", "fileName": "G.part1.rar"}, {"url": "https://a/2", "fileName": "G.part2.rar"}])
        self.assertEqual([d["unpack"] for d in json.loads(many["values"]["downloads"])], ["archive", "archive"])
        loose = gg.downloads_result("m", [{"url": "https://a/1", "fileName": "a.bin"}, {"url": "https://a/2", "fileName": "b.bin"}])
        self.assertNotIn("unpack", json.loads(loose["values"]["downloads"])[0])
        one = gg.downloads_result("m", [{"url": "https://a/1", "fileName": "a.zip"}])
        self.assertIn("download", one["values"])

    def test_pacing_waits_per_host(self):
        slept = []
        gg._sleep = slept.append
        clock = [1000.0]
        gg._clock = lambda: clock[0]
        try:
            gg.pace("https://a.example/1")
            gg.pace("https://a.example/2")
            gg.pace("https://b.example/1")
            self.assertEqual(slept, [gg.MIN_GAP])
        finally:
            import time

            gg._clock = time.monotonic


class Plugin(unittest.TestCase):
    def test_entry_points(self):
        p = gg.Plugin("Test")

        @p.on("ui.settings", "view")
        def _view(args):
            return gg.ok(gg.view("T", [gg.info("a", "A")]))

        @p.job("library.sources", "acquire")
        def _acquire(args, report):
            report(50, "half")
            return gg.done("Downloading", download={"url": "https://x/y", "fileName": "y.zip"})

        handle, start_job, cancel_job = p.entry_points()
        reply = json.loads(handle(json.dumps({"point": "ui.settings", "op": "view", "args": {}})))
        self.assertTrue(reply["ok"])
        self.assertEqual(json.loads(handle(json.dumps({"point": "x", "op": "y"})))["error"]["code"], "UNSUPPORTED")
        reports = []
        result = json.loads(start_job("j1", {"point": "library.sources", "op": "acquire", "args": {}}, lambda p, s: reports.append((p, s))))
        self.assertEqual(reports, [(50, "half")])
        self.assertEqual(json.loads(result["values"]["download"])["fileName"], "y.zip")


class Embed(unittest.TestCase):
    def test_embed(self):
        source = "import json\nimport gamegrab as gg  # embedded by build.sh\nX = gg.name_key('A b')\n"
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamegrab.py"), encoding="utf-8") as f:
            out = embed.embed(source, f.read())
        scope = {}
        exec(compile(out, "plugin.py", "exec"), scope)
        self.assertEqual(scope["X"], "ab")
        self.assertEqual(scope["gg"].__name__, "gamegrab")


if __name__ == "__main__":
    unittest.main()
