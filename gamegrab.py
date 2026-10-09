"""gamegrab: what the gamegrab-sources Python plugins for droidtop share.

A droidtop python-kind plugin is one file, plugin.py (droidtop docs/plugin-api.md
1.3). Each plugin repository keeps this file as a git submodule and its build.sh
embeds it into plugin.py as the module `gamegrab` (see `embed` in this repository's
README): the plugin's sources say `import gamegrab as gg`, and the shipped
plugin.py carries this file's text, executed once into a fresh module object.

Everything here assumes the plugin runs contained (docs/plugin-api.md 5.3): no
sockets and no files of its own. The network goes through droidtop's `net.http`,
`net.download` and `web.session`, state through droidtop's data API, and every
page a person sees is a view document droidtop draws (1.6).

Standard library only.
"""
import base64
import html as _html
import json
import re
import threading
import time
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse

VERSION = "0.2.0"

# ---------------------------------------------------------------- host calls


class HostError(Exception):
    """A host call droidtop refused or that failed: `code` is droidtop's error code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


_test_call = None


def use_host(fn):
    """Tests route host calls to `fn(api, op, args, version) -> reply dict` instead of droidtop."""
    global _test_call
    _test_call = fn


def raw_call(api, op, args=None, version=1):
    """One host call through droidtop's broker; the reply envelope as droidtop sent it."""
    if _test_call is not None:
        return _test_call(api, op, args or {}, version)
    import droidtop.host  # put in sys.modules by droidtop's bootstrap before plugin.py runs

    return droidtop.host.call(api, op, args or {}, version)


def call(api, op, args=None, version=1):
    """The reply's data, or HostError."""
    reply = raw_call(api, op, args, version)
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        error = (reply or {}).get("error") or {}
        raise HostError(str(error.get("code") or "FAILED"), str(error.get("message") or "%s %s failed" % (api, op)))
    data = reply.get("data")
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- pacing

# The least time between two requests to one site from this process, in seconds.
# Plugins set it once; every request here waits its turn per host.
MIN_GAP = 2.0
_pace_lock = threading.Lock()
_last_request = {}
_sleep = time.sleep
_clock = time.monotonic


def pace(url):
    host = (urlparse(url).hostname or "").lower()
    with _pace_lock:
        now = _clock()
        wait = _last_request.get(host, -1e9) + MIN_GAP - now
        _last_request[host] = max(now, now + wait)
    if wait > 0:
        _sleep(wait)


# ---------------------------------------------------------------- the network


class Answer:
    def __init__(self, status, url, body, truncated=False, headers=None):
        self.status = status
        self.url = url
        self.body = body
        self.truncated = truncated
        self.headers = headers or {}

    @property
    def ok(self):
        return 200 <= self.status < 300


def http(url, method="GET", headers=None, body=None, session=False, timeout_ms=30000):
    """One request; `session` sends it with the person's signed-in session on a site the
    plugin declared (`web.session fetch`), which droidtop adds itself. droidtop reads at
    most 128 KiB of an answer (`truncated` says there was more)."""
    pace(url)
    args = {"url": url, "method": method, "as": "text", "timeoutMs": timeout_ms}
    if headers:
        args["headers"] = headers
    if body is not None:
        args["body"] = body
    data = call("web.session" if session else "net", "fetch" if session else "http", args)
    return Answer(
        int(data.get("status") or 0),
        str(data.get("url") or url),
        str(data.get("body") or ""),
        bool(data.get("truncated")),
        data.get("headers") or {},
    )


def download_text(url, name, timeout_s=90):
    """A page too big for one answer: droidtop downloads it into the plugin's own data
    (`net.download`, a job), and it is read from there."""
    pace(url)
    job = call("net", "download", {"url": url, "name": name})["jobId"]
    deadline = _clock() + timeout_s
    while True:
        status = call("plugins", "job_status", {"jobId": job})
        if status.get("done"):
            if status.get("ok") is False:
                raise HostError(str(status.get("code") or "FAILED"), str(status.get("message") or "the download failed"))
            break
        if _clock() > deadline:
            try:
                call("plugins", "job_cancel", {"jobId": job})
            except HostError:
                pass
            raise HostError("TIMEOUT", "the page took too long to download")
        _sleep(0.25)
    return read_bytes(name).decode("utf-8", "replace")


def get_page(url, scratch_name, session=False):
    """A whole page: one `net.http` answer, or, when droidtop cut it, the page again through
    `net.download` (not offered with a signed-in session, which then keeps the cut answer)."""
    answer = http(url, session=session)
    if answer.truncated and answer.ok and not session:
        body = download_text(url, scratch_name)
        try:
            delete(scratch_name)
        except HostError:
            pass
        return Answer(answer.status, answer.url, body, False, answer.headers)
    return answer


# ---------------------------------------------------------------- the plugin's own data

_CHUNK = 120 * 1024


def read_bytes(name):
    out = bytearray()
    while True:
        data = call("data", "read", {"name": name, "offset": len(out), "length": _CHUNK, "as": "base64"})
        chunk = base64.b64decode(data.get("base64") or "")
        out += chunk
        if data.get("eof") or not chunk:
            return bytes(out)


def write_bytes(name, payload):
    offset = 0
    first = True
    while first or offset < len(payload):
        part = payload[offset : offset + _CHUNK]
        call("data", "write", {"name": name, "base64": base64.b64encode(part).decode("ascii"), "append": not first})
        first = False
        offset += len(part)


def read_json(name, default=None):
    """The plugin's file `name` as JSON, or `default` when there is none (or it is unreadable)."""
    try:
        raw = read_bytes(name)
    except HostError:
        return default
    if not raw:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return default


def write_json(name, value):
    write_bytes(name, json.dumps(value, separators=(",", ":")).encode("utf-8"))


def delete(name):
    call("data", "delete", {"name": name})


_cache_lock = threading.Lock()


def cached(key, max_age_s, produce, now=None):
    """`produce()`'s value, kept in the plugin's data for `max_age_s`. When the site fails, a
    stale copy is used rather than nothing (f95seeker's rule)."""
    name = "cache/" + re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:120] + ".json"
    now = time.time() if now is None else now
    with _cache_lock:
        kept = read_json(name)
    if isinstance(kept, dict) and now - float(kept.get("at", 0)) < max_age_s:
        return kept.get("value")
    try:
        value = produce()
    except (HostError, ValueError):
        if isinstance(kept, dict):
            return kept.get("value")
        raise
    with _cache_lock:
        try:
            write_json(name, {"at": now, "value": value})
        except HostError:
            pass  # over the plugin's data quota: the answer is still good this time
    return value


# ---------------------------------------------------------------- other host services


def notify(title, text):
    try:
        call("notify", "post", {"title": title, "text": text})
    except HostError:
        pass  # notifications turned off, or the hourly limit: the answer is still on the game's page


def signed_in():
    return call("web.session", "status", {}).get("signedIn") is True


def sign_in(url, done_cookie=None):
    args = {"url": url}
    if done_cookie:
        args["doneCookie"] = done_cookie
    return call("web.session", "sign_in", args).get("signedIn") is True


def sign_out():
    call("web.session", "clear", {})


def open_in_session(url):
    """Opens `url` in droidtop's web view with the plugin's session; the download the page
    starts (`{url, fileName, size?, session}`), or None."""
    data = call("web.session", "open_in_session", {"url": url})
    if data.get("captured") is not True:
        return None
    download = data.get("download")
    return download if isinstance(download, dict) else None


# Handing a link to another app: droidtop has no torrent client, so a magnet goes to a torrent
# app the person installed, and a page that needs a browser to the browser. droidtop's
# `apps.view {uri, title?}` (docs/plugin-api.md 3 F2, permission "Open links in other apps",
# Droidtop/tracker#418) shows Android's chooser, for https, http and magnet links only and only
# during a call the person started (a button's job). A droidtop without it, a refused
# permission, or no app that takes the link: the plugin shows the link to copy, with the reason.

NO_HANDOFF = "This version of droidtop cannot open links in other apps."
HANDOFF_DENIED = 'Allow "Open links in other apps" on this plugin\'s Permissions page to open it directly.'


def hand_off(uri, title):
    """Asks droidtop to open `uri` in another app through Android's chooser: (opened, reason),
    `reason` saying why not when it was not opened."""
    args = {"uri": uri}
    if title:
        args["title"] = title[:200]
    try:
        data = call("apps", "view", args)
    except HostError as e:
        return False, HANDOFF_DENIED if e.code == "PERMISSION_DENIED" else NO_HANDOFF
    if data.get("opened") is True:
        return True, None
    return False, str(data.get("reason") or "No app on this device opens this link") + "."


def handoff_result(uri, title, opened_message, hint=""):
    """A job's result for a hand-off button: a message when it opened, else a page with the link
    to copy and why."""
    opened, reason = hand_off(uri, title)
    if opened:
        return done(opened_message)
    why = reason.rstrip(".") + "." + (" " + hint if hint else "")
    return done("Copy the link into the app", view=handoff_fallback(title or "Link", uri, why))


# Split releases (docs/plugin-api.md 1.6, acquire `downloads`, Droidtop/tracker#419): with
# `unpack: "archive"` on every file, droidtop joins byte-split parts (X.7z.001 ...) and unpacks
# them, and places RAR volumes (X.part1.rar ...) together; the names must be the parts of one
# archive numbered 1 to N without a gap, or droidtop refuses the job. At most 16 files.
MAX_DOWNLOADS = 16


def split_part(name):
    """`X.part3.rar` -> ("x.rar", 3); `X.7z.002` -> ("x.7z", 2); anything else None."""
    name = (name or "").strip().lower()
    m = re.fullmatch(r"(.+)\.part0*(\d+)\.rar", name)
    if m:
        return m.group(1) + ".rar", int(m.group(2))
    m = re.fullmatch(r"(.+\.(?:7z|zip|rar))\.0*(\d+)", name)
    if m:
        return m.group(1), int(m.group(2))
    return None


def is_split_set(names):
    """The names are every part, 1 to N, of one split archive."""
    parts = [split_part(n) for n in names]
    if not parts or any(p is None for p in parts) or len({p[0] for p in parts}) != 1:
        return False
    return sorted(p[1] for p in parts) == list(range(1, len(parts) + 1))


def downloads_result(message, downloads, **values):
    """A job's result for several downloads as one Downloads job; split parts are marked to be
    joined and unpacked."""
    downloads = [dict(d) for d in downloads]
    if len(downloads) > 1 and is_split_set([d.get("fileName") for d in downloads]):
        for d in downloads:
            d["unpack"] = "archive"
    if len(downloads) == 1:
        return done(message, download=downloads[0], **values)
    return done(message, downloads=downloads, **values)


# ---------------------------------------------------------------- replies


def ok(data=None):
    return {"ok": True, "data": data or {}}


def error(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


def done(message, **values):
    out = {"message": message}
    for key, value in values.items():
        if value is not None:
            out[key] = value if isinstance(value, str) else json.dumps(value)
    return {"ok": True, "values": out}


def failed(message):
    return {"ok": False, "error": message}


# ---------------------------------------------------------------- views (docs/plugin-api.md 1.6)


def view(title, items, subtitle=None, sections=None):
    doc = {"view": 1, "title": title}
    if subtitle:
        doc["subtitle"] = subtitle
    doc["sections"] = sections if sections is not None else [{"id": "main", "items": [i for i in items if i]}]
    return doc


def section(id, items, title=None):
    out = {"id": id, "items": [i for i in items if i]}
    if title:
        out["title"] = title
    return out


def _node(kind, id, title, subtitle=None, **more):
    node = {"type": kind, "id": id, "title": title}
    if subtitle:
        node["subtitle"] = subtitle
    for key, value in more.items():
        if value is not None:
            node[key] = value
    return node


def info(id, title, value=None, subtitle=None):
    return _node("info", id, title, subtitle, value=value)


def button(id, title, action, subtitle=None, confirm=None, value=None):
    return _node("button", id, title, subtitle, action=action, confirm=confirm, value=value)


def row(id, title, subtitle=None, columns=None, badges=None, value=None, action=None):
    return _node("row", id, title, subtitle, columns=columns or None, badges=badges or None, value=value, action=action)


def toggle(id, title, value, action=None, subtitle=None):
    return _node("toggle", id, title, subtitle, value=bool(value), action=action)


def choice(id, title, options, value=None, action=None, subtitle=None):
    return _node("choice", id, title, subtitle, options=[{"value": v, "label": l} for v, l in options], value=value, action=action)


def text(id, title, value="", action=None, subtitle=None):
    return _node("text", id, title, subtitle, value=value, action=action)


def job(op, title, args=None):
    out = {"kind": "job", "op": op, "title": title}
    if args:
        out["args"] = args
    return out


def call_action(op, args=None):
    out = {"kind": "call", "op": op}
    if args:
        out["args"] = args
    return out


def view_action(op, args=None):
    out = {"kind": "view", "op": op}
    if args:
        out["args"] = args
    return out


def cut(value, limit):
    value = value or ""
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def handoff_fallback(title, uri, why):
    """The page shown when droidtop cannot open a link in another app: the link itself, to copy."""
    return view(
        title,
        [
            info("why", "Copy this link into the app", subtitle=why),
            text("link", "Link", uri),
        ],
    )


# ---------------------------------------------------------------- the plugin's entry points


class Plugin:
    """Answers droidtop's calls by extension point and op. `on(point, op)` registers a quick
    call `fn(args) -> reply`; `job(point, op)` a job `fn(args, report) -> result`."""

    def __init__(self, label):
        self.label = label
        self.calls = {}
        self.jobs = {}
        self.cancelled = set()

    def on(self, point, op):
        def register(fn):
            self.calls[(point, op)] = fn
            return fn

        return register

    def job(self, point, op):
        def register(fn):
            self.jobs[(point, op)] = fn
            return fn

        return register

    def handle(self, envelope):
        point = envelope.get("point")
        op = envelope.get("op")
        args = envelope.get("args") or {}
        fn = self.calls.get((point, op))
        if fn is None:
            return error("UNSUPPORTED", "not offered: %s %s" % (point, op))
        try:
            return fn(args)
        except HostError as e:
            return error("PERMISSION_DENIED" if e.code == "PERMISSION_DENIED" else "FAILED", e.message)
        except (ValueError, KeyError, IndexError) as e:
            return error("FAILED", "%s answered with something unexpected (%s)" % (self.label, e))

    def run_job(self, job_id, envelope, report):
        point = envelope.get("point")
        op = envelope.get("op")
        args = envelope.get("args") or {}
        fn = self.jobs.get((point, op))
        if fn is None:
            return failed("not offered: %s %s" % (point, op))
        try:
            return fn(args, report)
        except HostError as e:
            return failed(e.message)
        except (ValueError, KeyError, IndexError) as e:
            return failed("%s answered with something unexpected (%s)" % (self.label, e))
        finally:
            self.cancelled.discard(job_id)

    def entry_points(self):
        """The module-level functions droidtop calls in plugin.py (docs/plugin-api.md 1.3)."""

        def handle(call_json):
            return json.dumps(self.handle(json.loads(call_json)))

        def start_job(job_id, call, report):
            if isinstance(call, str):
                call = json.loads(call)
            return json.dumps(self.run_job(job_id, call or {}, report))

        def cancel_job(job_id):
            self.cancelled.add(job_id)
            return "{}"

        return handle, start_job, cancel_job


# ---------------------------------------------------------------- text and html


def unescape(value):
    return _html.unescape(value or "")


def strip_tags(fragment):
    """Visible text of an HTML fragment: tags out, entities decoded, whitespace collapsed."""
    fragment = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment or "")
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", fragment)
    text = unescape(re.sub(r"<[^>]+>", " ", fragment))
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def one_line(fragment):
    return re.sub(r"\s+", " ", strip_tags(fragment)).strip()


_A = re.compile(r"(?is)<a\b([^>]*)>(.*?)</a>")
_HREF = re.compile(r"""(?is)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def links(fragment, base=None):
    """Every `<a href>` in `fragment`: (absolute href, visible text), in page order."""
    out = []
    for m in _A.finditer(fragment or ""):
        h = _HREF.search(m.group(1))
        if not h:
            continue
        href = unescape(h.group(1) or h.group(2) or h.group(3) or "").strip()
        if base and not re.match(r"(?i)^[a-z][a-z0-9+.-]*:", href):
            href = urljoin(base, href)
        out.append((href, one_line(m.group(2))))
    return out


def name_key(name):
    """A title compared without case, spaces or punctuation (droidtop's GameNaming.nameKey)."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def words(query):
    return [w for w in re.split(r"[^a-z0-9]+", (query or "").lower()) if w]


def matches_all(title, query):
    """Every word of `query` appears in `title` (a local search over a list the site gave)."""
    key = " " + " ".join(words(title)) + " "
    return all(w in key for w in words(query))


def human_size(size_text):
    return re.sub(r"\s+", " ", (size_text or "").strip())


# ---------------------------------------------------------------- feeds


def _tag(item, name):
    m = re.search(r"(?is)<%s\b[^>]*>(.*?)</%s>" % (re.escape(name), re.escape(name)), item)
    if not m:
        return None
    value = m.group(1).strip()
    cdata = re.fullmatch(r"(?s)<!\[CDATA\[(.*)\]\]>", value)
    return cdata.group(1) if cdata else unescape(value)


def rss_items(xml_text, tags=()):
    """The `<item>`s of an RSS feed, read leniently (sites publish feeds that are not
    well-formed XML): title, link, guid, pubDate, description, categories, and `tags`."""
    items = []
    for raw in re.findall(r"(?is)<item\b[^>]*>(.*?)</item>", xml_text or ""):
        item = {
            "title": unescape(_tag(raw, "title") or "").strip(),
            "link": (_tag(raw, "link") or "").strip(),
            "guid": (_tag(raw, "guid") or "").strip(),
            "pubDate": (_tag(raw, "pubDate") or "").strip(),
            "description": _tag(raw, "description") or "",
            "categories": [unescape(c).strip() for c in re.findall(r"(?is)<category\b[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</category>", raw)],
        }
        for t in tags:
            item[t] = _tag(raw, t)
        items.append(item)
    return items


# ---------------------------------------------------------------- torrents

TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://exodus.desync.com:6969/announce",
)


def magnet(info_hash, name, trackers=TRACKERS):
    uri = "magnet:?xt=urn:btih:" + info_hash
    if name:
        uri += "&dn=" + quote_plus(name)
    for tracker in trackers:
        uri += "&tr=" + quote(tracker, safe="")
    return uri


def magnet_hash(uri):
    m = re.search(r"(?i)xt=urn:btih:([0-9a-z]+)", uri or "")
    return m.group(1).lower() if m else None


TORRENT_NOTE = "droidtop has no torrent client: this hands the link to a torrent app you have installed."


# ---------------------------------------------------------------- XenForo forums
#
# Thread titles, prefixes and pages as XenForo 2 draws them (F95zone, LewdCorner).
# Ported from the F95zone plugin (gamegrab-sources/droidtop-plugin-f95, Dart:
# csrfToken, watchedThreads, F95Thread) and droidtop's former core F95Thread.


def thread_id(text, domain):
    """The thread id in whatever a person pastes: the thread's link
    (`https://<domain>/threads/<slug>.<id>/`), the short form, or the bare number."""
    text = (text or "").strip()
    if re.fullmatch(r"\d+", text):
        n = int(text)
        return n if n > 0 else None
    m = re.search(r"(?i)%s/threads/(?:[^/?#\s]*\.)?(\d+)" % re.escape(domain), text)
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    return None


def csrf_token(page):
    m = re.search(r"""data-csrf\s*=\s*["']([^"']+)["']""", page or "")
    return m.group(1) if m else None


def split_title(title):
    """`Name [v0.5] [Developer]` -> (name, version, developer). The version is the bracket that
    reads like one (starts with v, a digit, Ep, Ch, Build, Final, ...); the developer is the
    last bracket after it."""
    brackets = re.findall(r"\[([^\]]+)\]", title or "")
    name = re.sub(r"\s*\[[^\]]*\]", "", title or "").strip()
    version = None
    developer = None
    for i, b in enumerate(brackets):
        if version is None and re.match(r"(?i)^(v\s*\d|\d|ep|ch|chapter|episode|season|build|final|r\d|alpha|beta|demo|day|part|update)", b.strip()):
            version = b.strip()
            if i + 1 < len(brackets):
                developer = brackets[-1].strip()
    if version is None and len(brackets) == 1:
        developer = brackets[0].strip()
    return name, version, developer


def labels(fragment):
    return [one_line(m).strip("[] ") for m in re.findall(r'(?is)<span class="label(?:\s[^"]*)?"[^>]*>(.*?)</span>', fragment or "")]


def thread_list(page, domain):
    """Thread rows of a forum listing (`structItem--thread`) or search results (`contentRow`):
    [{id, title, name, version, developer, labels, url}]."""
    out = []
    seen = set()
    blocks = re.split(r'(?i)(?=<div[^>]+class="structItem structItem--thread|<li[^>]+class="block-row)', page or "")
    for block in blocks[1:]:
        title_html = None
        m = re.search(r'(?is)<div class="structItem-title"[^>]*>(.*?)</div>', block)
        if m:
            title_html = m.group(1)
        else:
            m = re.search(r'(?is)<h3 class="contentRow-title"[^>]*>(.*?)</h3>', block)
            if m:
                title_html = m.group(1)
        if not title_html:
            continue
        tid = None
        for href, _ in links(title_html, "https://%s/" % domain):
            tid = thread_id(href, domain)
            if tid:
                break
        if not tid or tid in seen:
            continue
        seen.add(tid)
        tags = labels(title_html)
        primary = re.search(r'(?is)<a\b[^>]*data-tp-primary="on"[^>]*>(.*?)</a>', title_html)
        title = one_line(primary.group(1)) if primary else one_line(re.sub(r'(?is)<span class="label(?:\s[^"]*)?"[^>]*>.*?</span>', "", title_html))
        for tag in tags:
            if title.startswith(tag + " "):
                title = title[len(tag) + 1 :]
        name, version, developer = split_title(title)
        out.append({"id": tid, "title": title, "name": name, "version": version, "developer": developer, "labels": tags, "url": "https://%s/threads/%d/" % (domain, tid)})
    return out


def thread_page(page, domain):
    """A thread page: {title, name, version, developer, labels, first_post (html), canonical}."""
    m = re.search(r'(?is)<h1 class="p-title-value"[^>]*>(.*?)</h1>', page or "")
    head = m.group(1) if m else ""
    tags = labels(head)
    head = re.sub(r"(?is)<i\b.*?</i>", "", head)
    head = re.sub(r'(?is)<span class="label(?:\s[^"]*)?"[^>]*>.*?</span>', "", head)
    title = one_line(head)
    if not title:
        t = re.search(r"(?is)<title>(.*?)</title>", page or "")
        title = one_line(t.group(1)).rsplit(" | ", 1)[0] if t else ""
    name, version, developer = split_title(title)
    post = re.search(r'(?is)<article[^>]+class="message[^"]*message--post.*?<div class="bbWrapper">(.*?)</div>\s*(?:<div class="js-selectToQuoteEnd">|</article>)', page or "")
    canonical = re.search(r'(?i)<link rel="canonical" href="([^"]+)"', page or "")
    return {
        "title": title,
        "name": name,
        "version": version,
        "developer": developer,
        "labels": tags,
        "first_post": post.group(1) if post else "",
        "canonical": canonical.group(1) if canonical else None,
    }


def watched_threads(page, domain):
    """The threads a watched-threads page lists: thread id -> title (`data-tp-primary="on"`)."""
    out = {}
    for m in re.finditer(r'(?is)<a\s([^>]*data-tp-primary\s*=\s*"on"[^>]*)>(.*?)</a>', page or ""):
        h = _HREF.search(m.group(1))
        if not h:
            continue
        href = h.group(1) or h.group(2) or h.group(3) or ""
        tid = thread_id(("%s%s" % (domain, href)) if href.startswith("/") else href, domain)
        if tid:
            out[tid] = one_line(m.group(2))
    return out


# droidtop's engines-database ids for forum prefixes that name one engine (droidtop
# EngineRegistryParser.ENGINE_IDS); the acquire reply's engine hint. RPG Maker is left out
# on purpose: it is several engines, and droidtop's own detection tells them apart.
ENGINE_PREFIXES = {
    "ren'py": "renpy",
    "renpy": "renpy",
    "html": "html",
    "godot": "godot",
    "unity": "unity",
    "unreal engine": "unreal",
    "unreal": "unreal",
}


def engine_of(tags):
    for tag in tags or ():
        engine = ENGINE_PREFIXES.get((tag or "").strip().lower())
        if engine:
            return engine
    return None
