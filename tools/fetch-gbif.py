#!/usr/bin/env python3
"""fetch-gbif.py: one GBIF occurrence download (DESIGN §12.7, step 18): every occurrence of one year that has
coordinates, as GBIF's "simple CSV" (tab-separated, one .csv in a zip). GBIF prepares a download on its servers (minutes
to hours) for a registered user. GBIF's work is costly, so a download is asked for at most once: first the user's own
recent downloads are searched for one with the same query (a run stopped after asking, or an answer lost on the way,
finds its download there), and the request itself is never retried. Its key is kept in OUT_DIR/state.json, so a rerun
waits for the same download. The zip is written under a temporary name first and kept only when its size = GBIF's, it
holds exactly one .csv and that file's CRC checks out (a kept zip is checked again); GBIF's description of the download
(its DOI, which must be cited, and totalRecords, the rows it holds) is kept as OUT_DIR/download.json.
The login comes from a netrc file (machine api.gbif.org, login = the GBIF username, not the email), by default
~/.config/gpstiles/gbif.netrc, readable by its owner only. It is never printed, and only sent over https (or to this
Mac), never on a redirect.
Usage: tools/fetch-gbif.py OUT_DIR YEAR [--url URL] [--netrc FILE] [--poll SECONDS]
Built-in modules only."""
import argparse
import base64
import json
import netrc
import os
import pathlib
import signal
import ssl
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

API = "https://api.gbif.org/v1"
AGENT = "gpstiles fetch-gbif.py (test data for a local map)"
MACOS_CERTS = "/etc/ssl/cert.pem"  # python.org's Python brings no certificates: use macOS's. Checks stay on.
CHUNK = 1 << 20
TRIES = 3
DONE = {"SUCCEEDED"}
WAITING = {"PREPARING", "RUNNING", "SUSPENDED"}
FAILED = {"FAILED", "KILLED", "CANCELLED", "FILE_ERASED"}
LOCAL = {"127.0.0.1", "localhost", "::1"}
KEY = re.compile(r"[0-9A-Za-z]{1,40}(-[0-9A-Za-z]{1,40}){0,3}")  # GBIF's are like 0012345-241107131044228


class FetchError(Exception):
    pass


def checked_key(key, source):
    """A download key, whichever answer or file it came from: it becomes a file name and a URL path, so letters,
    digits and inner hyphens only (no '/', '..', or anything else)."""
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise FetchError(f"{source} gave {str(key)[:100]!r}, not a GBIF download key")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A request carrying the login must not follow a redirect: urllib would send the login on to the new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchError(f"{req.full_url} redirected to {newurl}: not followed with the login")


def tls():
    context = ssl.create_default_context()
    if os.path.exists(MACOS_CERTS):
        context.load_verify_locations(MACOS_CERTS)
    return context


def login(path):
    """(user, password) for api.gbif.org from a netrc file only its owner can read."""
    path = pathlib.Path(path).expanduser()
    if not path.exists():
        raise FetchError(f"no {path}: put 'machine api.gbif.org login USER password PASSWORD' in it (chmod 600)")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise FetchError(f"{path} can be read by others: chmod 600 it")
    try:
        entry = netrc.netrc(path).authenticators("api.gbif.org")
    except netrc.NetrcParseError:  # its message quotes the file (a password with a space in it, say): not shown
        raise FetchError(f"{path} isn't a netrc file netrc can read (a password with spaces must be quoted)") from None
    if entry is None or not entry[0] or not entry[2] or entry[0].startswith("YOUR_"):
        raise FetchError(f"{path} has no GBIF login for api.gbif.org")
    return entry[0], entry[2]


def call(url, *, data=None, auth=None, timeout=120, retry=True):
    """The answer to a GET (or POST of JSON). auth: (user, password), sent only over https (or to this Mac) and never on
    a redirect. retry: on connection errors and 5xx answers; never for a request that may start work at GBIF."""
    headers = {"User-Agent": AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    handlers = [urllib.request.HTTPSHandler(context=tls())]
    if auth is not None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" and parts.hostname not in LOCAL:
            raise FetchError(f"{url}: the login goes only over https")
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        handlers.append(NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    for attempt in range(TRIES if retry else 1):
        if attempt:
            time.sleep(10 * 2 ** attempt)
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
            return opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise FetchError(f"{url}: HTTP {e.code}: GBIF refused the login") from None
            if e.code < 500 or attempt == TRIES - 1 or not retry:
                raise FetchError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == TRIES - 1 or not retry:
                raise FetchError(f"{url}: {getattr(e, 'reason', e)}") from None
    raise FetchError(url)


def query(year, user):
    return {"creator": user, "sendNotification": False, "format": "SIMPLE_CSV",
            "predicate": {"type": "and", "predicates": [
                {"type": "equals", "key": "HAS_COORDINATE", "value": "true"},
                {"type": "equals", "key": "YEAR", "value": str(year)}]}}


def same_query(request, wanted):
    """True when a download's request asks what `wanted` asks (GBIF may write keys in another case or order)."""
    def norm(p):
        if not isinstance(p, dict):
            return p
        out = {k.lower(): (str(v).upper() if k.lower() in ("key", "type") else str(v).lower() if k.lower() == "value" else v)
               for k, v in p.items() if k.lower() not in ("matchcase", "checklistkey")}
        if "predicates" in out:
            out["predicates"] = sorted((norm(q) for q in out["predicates"]), key=json.dumps)
        return out
    return (str(request.get("format", "")).upper() == wanted["format"]
            and json.dumps(norm(request.get("predicate")), sort_keys=True) == json.dumps(norm(wanted["predicate"]), sort_keys=True))


def earlier_download(api, auth, wanted):
    """The key of the user's newest download with the same query that hasn't failed, or None (the 100 newest are read)."""
    with call(f"{api}/occurrence/download/user/{urllib.parse.quote(auth[0])}?limit=100", auth=auth) as answer:
        found = json.loads(answer.read()).get("results", [])
    for item in sorted(found, key=lambda d: str(d.get("created", "")), reverse=True):
        if item.get("status") in DONE | WAITING and same_query(item.get("request") or {}, wanted):
            return checked_key(item.get("key"), "GBIF's list of your downloads")
    return None


def write_state(path, state):
    """state.json, replaced whole: a stop while writing leaves the old one."""
    part = path.with_suffix(".json.part")
    part.write_text(json.dumps(state) + "\n")
    os.replace(part, path)


def whole_zip(path, size):
    """True when the zip is `size` bytes, holds exactly one .csv and every byte of it matches its CRC. Python reads
    stored and deflated zips; for one compressed another way (Deflate64, which big zips may use) macOS's unzip checks it."""
    try:
        if path.stat().st_size != size:
            return False
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if len(names) != 1 or not names[0].endswith(".csv"):
                return False
            try:
                return z.testzip() is None
            except NotImplementedError:  # a compression Python can't read
                return subprocess.run(["unzip", "-tqq", str(path)], capture_output=True).returncode == 0
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, zlib.error):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("year", type=int)
    parser.add_argument("--url", default=API)
    parser.add_argument("--netrc", default="~/.config/gpstiles/gbif.netrc")
    parser.add_argument("--poll", type=float, default=120.0)
    args = parser.parse_args()
    if not 1600 <= args.year <= 2100:
        print(f"fetch-gbif: want a year, not {args.year}", file=sys.stderr)
        return 2
    for sig in (signal.SIGTERM, signal.SIGHUP):  # a stop runs the clean-up below: no .part is left
        signal.signal(sig, lambda *_: sys.exit(1))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    api = args.url.rstrip("/")
    state_file = out / "state.json"
    part = None
    try:
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if state.get("key"):
            checked_key(state["key"], str(state_file))
        if state and state.get("year") != args.year:
            raise FetchError(f"{out} holds the download of {state.get('year')}, not {args.year}: use another folder")
        if not state.get("key"):
            auth = login(args.netrc)
            wanted = query(args.year, auth[0])
            key = earlier_download(api, auth, wanted)
            if key:
                print(f"fetch-gbif: using download {key}, asked for earlier", flush=True)
            else:
                try:  # never retried: GBIF may have taken it even when the answer is lost
                    with call(f"{api}/occurrence/download/request", data=json.dumps(wanted).encode(), auth=auth,
                              retry=False) as answer:
                        key = answer.read().decode().strip()
                except FetchError as e:
                    raise FetchError(f"{e}. GBIF may still have taken the request: a rerun looks for it first") from None
                checked_key(key, "GBIF's answer to the request")
                print(f"fetch-gbif: GBIF is preparing download {key}", flush=True)
            state = {"year": args.year, "key": key}
            write_state(state_file, state)
        key = state["key"]
        while True:
            with call(f"{api}/occurrence/download/{urllib.parse.quote(key)}") as answer:
                info = json.loads(answer.read())
            status = info.get("status")
            if status in DONE:
                break
            if status in FAILED:
                raise FetchError(f"GBIF's download {key} ended {status}: remove {state_file} to ask again")
            if status not in WAITING:
                raise FetchError(f"GBIF's download {key} has the status {status!r}, which this script doesn't know")
            print(f"fetch-gbif: {key} is {status}; asking again in {args.poll:g} s", flush=True)
            time.sleep(args.poll)
        size = int(info["size"])
        name = f"{key}.zip"
        (out / "download.json").write_text(json.dumps(info, indent=1) + "\n")
        target = out / name
        # A kept zip is checked whole once; after that its size and time stand for it (a full year takes minutes).
        stamp = [size, target.stat().st_mtime_ns] if target.exists() else None
        if stamp is not None and state.get("checked") == stamp and target.stat().st_size == size:
            print(f"fetch-gbif: {name} {size} bytes (checked before), {info.get('totalRecords')} records, DOI {info.get('doi')}")
            return 0
        if not whole_zip(target, size):
            target.unlink(missing_ok=True)  # a damaged kept zip goes: a failed download below leaves nothing
            part = out / (name + ".part")
            with call(info.get("downloadLink") or f"{api}/occurrence/download/request/{name}", timeout=600) as answer, \
                    open(part, "wb") as f:
                while block := answer.read(CHUNK):
                    f.write(block)
            if not whole_zip(part, size):
                raise FetchError(f"{name}: {part.stat().st_size} bytes (GBIF says {size}), or not a zip holding one "
                                 "whole .csv (size, CRC)")
            os.replace(part, target)
            part = None
        write_state(state_file, {**state, "checked": [size, target.stat().st_mtime_ns]})
        print(f"fetch-gbif: {name} {size} bytes, {info.get('totalRecords')} records, DOI {info.get('doi')}")
        return 0
    except (FetchError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"fetch-gbif: {e}", file=sys.stderr)
        return 1
    finally:
        if part is not None:
            part.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
