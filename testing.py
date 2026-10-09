"""A fake droidtop host for the plugins' tests: serves pages from fixtures by URL, keeps the
plugin's data in memory, and records every host call. Not shipped in any bundle."""
import base64
import json


class FakeHost:
    def __init__(self, pages=None, signed_in=False):
        # url -> (status, body) or body; a callable(url) -> (status, body) for anything else
        self.pages = dict(pages or {})
        self.files = {}
        self.calls = []
        self.signed_in = signed_in
        self.handoff = True  # droidtop's apps.view; see the "apps view" case below
        self.captured = None
        self.notes = []
        self.max_body = 128 * 1024
        self.jobs = {}

    def page(self, url):
        hit = self.pages.get(url)
        if hit is None:
            for key, value in self.pages.items():
                if callable(key) and key(url):
                    hit = value
                    break
        if hit is None:
            return 404, "not found: " + url
        if isinstance(hit, tuple):
            return hit
        return 200, hit

    def __call__(self, api, op, args, version):
        self.calls.append((api, op, args))
        key = api + " " + op
        if key in ("net http", "web.session fetch"):
            if key == "web.session fetch" and not self.signed_in:
                status, body = 403, "<title>Just a moment...</title>"
            else:
                status, body = self.page(args["url"])
            raw = body.encode("utf-8")
            data = {"status": status, "url": args["url"], "body": raw[: self.max_body].decode("utf-8", "ignore"), "truncated": len(raw) > self.max_body}
            if key == "web.session fetch":
                data["signedIn"] = self.signed_in
            return {"ok": True, "data": data}
        if key == "net download":
            status, body = self.page(args["url"])
            if status != 200:
                return {"ok": False, "error": {"code": "FAILED", "message": "HTTP %d" % status}}
            self.files[args["name"]] = body.encode("utf-8")
            job = "j%d" % len(self.jobs)
            self.jobs[job] = True
            return {"ok": True, "data": {"jobId": job, "name": args["name"]}}
        if key == "plugins job_status":
            return {"ok": True, "data": {"done": True, "ok": True, "data": {}}}
        if key == "data read":
            if args["name"] not in self.files:
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "no data named " + args["name"]}}
            blob = self.files[args["name"]]
            start = args.get("offset", 0)
            part = blob[start : start + args.get("length", 1 << 20)]
            return {"ok": True, "data": {"base64": base64.b64encode(part).decode(), "eof": start + len(part) >= len(blob)}}
        if key == "data write":
            part = base64.b64decode(args["base64"])
            self.files[args["name"]] = (self.files.get(args["name"], b"") if args.get("append") else b"") + part
            return {"ok": True, "data": {"size": len(self.files[args["name"]])}}
        if key == "data delete":
            self.files.pop(args["name"], None)
            return {"ok": True, "data": {"deleted": True}}
        if key == "web.session status":
            return {"ok": True, "data": {"signedIn": self.signed_in}}
        if key == "web.session sign_in":
            self.signed_in = True
            return {"ok": True, "data": {"signedIn": True}}
        if key == "web.session clear":
            self.signed_in = False
            return {"ok": True, "data": {"cleared": True}}
        if key == "web.session open_in_session":
            captured = self.captured(args["url"]) if callable(self.captured) else self.captured
            if captured is None:
                return {"ok": True, "data": {"captured": False}}
            return {"ok": True, "data": {"captured": True, "download": dict(captured, url=captured.get("url", args["url"]))}}
        if key == "notify post":
            self.notes.append(args)
            return {"ok": True, "data": {"posted": True}}
        if key == "apps view":
            # handoff: False = an older droidtop without apps.view, "denied" = permission refused,
            # "none" = no app takes the link, True = opened.
            if self.handoff is False:
                return {"ok": False, "error": {"code": "UNSUPPORTED", "message": "no such host api: apps view"}}
            if self.handoff == "denied":
                return {"ok": False, "error": {"code": "PERMISSION_DENIED", "message": "not allowed"}}
            if self.handoff == "none":
                return {"ok": True, "data": {"opened": False, "reason": "no app opens magnet links"}}
            return {"ok": True, "data": {"opened": True}}
        return {"ok": False, "error": {"code": "UNSUPPORTED", "message": "fake host: " + key}}

    def requests(self):
        return [a["url"] for api, op, a in self.calls if (api, op) in (("net", "http"), ("web.session", "fetch"), ("net", "download"))]


def install(gg, host):
    """Routes `gg`'s host calls to `host` and makes pacing instant."""
    gg.use_host(host)
    gg._sleep = lambda s: None
    gg._last_request.clear()
    return host


def envelope(point, op, args=None):
    return json.dumps({"contract": 2, "callId": "t", "point": point, "version": 1, "op": op, "args": args or {}})
