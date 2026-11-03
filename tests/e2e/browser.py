"""browser.py: drives headless Google Chrome over its DevTools pipe, with built-in modules only, for the page
tests (step 6+) and the validations: open a page, run JavaScript in it, click and drag with the real mouse,
take a screenshot. Records the page's script errors, console warnings and errors, and Content-Security-Policy
violations. Unless asked, every host but 127.0.0.1 is unreachable, so tests never load the internet base map."""
import base64
import json
import os
import pathlib
import select
import shutil
import subprocess
import tempfile
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Runs in the page before its own scripts: keeps every blocked load or script (CSP) for the tests to read,
# and lets the browser's list of requests (Resource Timing) grow past its default 250.
PAGE_SETUP = """window.__violations = [];
document.addEventListener("securitypolicyviolation", (e) => window.__violations.push(`${e.violatedDirective} ${e.blockedURI}`));
performance.setResourceTimingBufferSize(100000);"""


def available():
    return os.path.exists(CHROME)


class Browser:
    """One headless Chrome with one tab of width × height pixels, closed on exit."""

    def __init__(self, width=1200, height=800, internet=False):
        self.profile = tempfile.mkdtemp()  # removed in close(), errors ignored: Chrome may still be writing (Python 3.9 has no ignore_cleanup_errors)
        self.buffer = bytearray()
        self.next_id = 0
        self.session = None
        self.errors = []  # uncaught script errors in the page
        self.log = []  # console and browser warnings and errors: {"source", "level", "text"}
        to_chrome, self.writer = os.pipe()
        self.reader, from_chrome = os.pipe()

        def pipes():  # Chrome reads commands on fd 3 and writes answers on fd 4 (--remote-debugging-pipe)
            a, b = os.dup(to_chrome), os.dup(from_chrome)  # never 3 and 4 the wrong way round
            os.dup2(a, 3)
            os.dup2(b, 4)

        args = [CHROME, "--headless=new", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
                "--disable-gpu", "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--hide-scrollbars", "--mute-audio", "--js-flags=--max-old-space-size=512",  # a runaway page stops at 512 MB
                f"--user-data-dir={self.profile}",
                f"--window-size={width},{height}", "about:blank"]
        if not internet:
            args.insert(1, "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1")
        # close_fds=False keeps the two pipes that pipes() puts at 3 and 4; Python opens every other file
        # non-inheritable, so nothing else reaches Chrome.
        try:
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, close_fds=False, preexec_fn=pipes)
        except BaseException:  # Chrome didn't start: nothing else will clean these up (Claude skeptic, step 18)
            for fd in (to_chrome, from_chrome, self.reader, self.writer):
                os.close(fd)
            shutil.rmtree(self.profile, ignore_errors=True)
            raise
        os.close(to_chrome)
        os.close(from_chrome)
        try:
            target = self.call("Target.createTarget", session=False, url="about:blank")["targetId"]
            self.session = self.call("Target.attachToTarget", session=False, targetId=target, flatten=True)["sessionId"]
            self.call("Runtime.enable")
            self.call("Page.enable")
            self.call("Log.enable")
            self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
            self.call("Page.addScriptToEvaluateOnNewDocument", source=PAGE_SETUP)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.call("Browser.close", session=False, timeout=5)
        except Exception:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for fd in (self.reader, self.writer):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)

    def _read(self, deadline):
        """The next message from Chrome (each ends with a zero byte)."""
        while (end := self.buffer.find(b"\0")) < 0:
            ready, _, _ = select.select([self.reader], [], [], max(deadline - time.monotonic(), 0))
            if not ready:
                raise TimeoutError("Chrome didn't answer in time")
            chunk = os.read(self.reader, 1 << 20)
            if not chunk:
                raise EOFError("Chrome closed its pipe")
            self.buffer += chunk
        message = json.loads(self.buffer[:end])
        del self.buffer[:end + 1]
        return message

    def call(self, method, session=True, timeout=30, **params):
        """Sends one DevTools command and returns its result (raises on an error answer)."""
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = self.session
        data = json.dumps(message).encode() + b"\0"
        while data:
            data = data[os.write(self.writer, data):]
        deadline = time.monotonic() + timeout
        while True:
            answer = self._read(deadline)
            if answer.get("id") == self.next_id:
                if "error" in answer:
                    raise RuntimeError(f"{method}: {answer['error']}")
                return answer.get("result", {})
            event, params = answer.get("method"), answer.get("params", {})
            if event == "Runtime.exceptionThrown":
                details = params["exceptionDetails"]
                self.errors.append(details.get("exception", {}).get("description") or details.get("text"))
            elif event == "Log.entryAdded" and params["entry"]["level"] in ("warning", "error"):
                entry = params["entry"]
                self.log.append({"source": entry["source"], "level": entry["level"], "text": entry["text"],
                                 "url": entry.get("url", "")})
            elif event == "Runtime.consoleAPICalled" and params["type"] in ("warning", "error"):
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in params["args"])
                self.log.append({"source": "console", "level": params["type"], "text": text, "url": ""})

    def open(self, url):
        self.call("Page.navigate", url=url)

    def reload(self):
        self.call("Page.reload")

    def page_log(self):
        """Warnings and errors of the page itself: everything but the base map's tiles failing to load (the
        tests block the internet). The page's own failed requests stay in."""
        self.js("0")  # reads any event that came in since the last call
        return [e for e in self.log if not e["url"].startswith("https://tile.openstreetmap.org/")]

    def js(self, expression):
        """The value of a JavaScript expression in the page (promises are awaited)."""
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{expression}: {result['exceptionDetails'].get('exception', {}).get('description')}")
        return result["result"].get("value")

    def wait(self, expression, timeout=20):
        """Waits until the expression is truthy in the page and returns its value. An error (the page not
        there yet) counts as not yet; the last one is shown if time runs out."""
        deadline, last = time.monotonic() + timeout, None
        while True:
            try:
                if value := self.js(expression):
                    return value
            except RuntimeError as error:
                last = error
            if time.monotonic() > deadline:
                raise TimeoutError(f"still not true after {timeout} s: {expression}" + (f" (last error: {last})" if last else ""))
            time.sleep(0.1)

    def violations(self):
        return self.js("window.__violations || []")

    def problems(self):
        """Everything that went wrong on the page so far: script errors, CSP violations, console warnings and
        errors. Read last, after a call, so nothing that just happened is missed."""
        violations, log = self.violations(), self.page_log()
        return {"errors": self.errors, "violations": violations, "log": log} if self.errors or violations or log else {}

    def mouse(self, kind, x, y, button="none", buttons=0, modifiers=0):
        """One real mouse event at page pixel (x, y): mouseMoved, mousePressed or mouseReleased."""
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button, buttons=buttons,
                  clickCount=0 if button == "none" else 1, modifiers=modifiers)

    def center_of(self, selector):
        return self.js(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
                       " return [r.x + r.width / 2, r.y + r.height / 2]; })()")

    def click(self, selector):
        """Clicks the middle of the first element matching the CSS selector, like a person would."""
        x, y = self.center_of(selector)
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y, "left", 1)
        self.mouse("mouseReleased", x, y, "left", 0)

    def drag(self, start, end, steps=8, modifiers=0):
        """Presses the left button at start, moves to end in steps, releases there."""
        (x0, y0), (x1, y1) = start, end
        self.mouse("mouseMoved", x0, y0, modifiers=modifiers)
        self.mouse("mousePressed", x0, y0, "left", 1, modifiers)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, "left", 1, modifiers)
        self.mouse("mouseReleased", x1, y1, "left", 0, modifiers)

    def save_downloads_in(self, folder):
        """Files the page downloads (a click on a download link) go to this folder, under their own names."""
        self.call("Browser.setDownloadBehavior", session=False, behavior="allow", downloadPath=str(folder))

    def wait_for_download(self, path, timeout=60):
        """Waits until the download has finished (Chrome writes it under another name, then renames it)."""
        deadline = time.monotonic() + timeout
        while not pathlib.Path(path).exists():
            if time.monotonic() > deadline:
                raise TimeoutError(f"no {path} after {timeout} s")
            time.sleep(0.1)
            self.js("0")  # keeps reading Chrome's messages
        return pathlib.Path(path).read_bytes()

    def screenshot(self, path):
        data = self.call("Page.captureScreenshot", format="png", timeout=60)["data"]
        pathlib.Path(path).write_bytes(base64.b64decode(data))
