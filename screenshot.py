#!/usr/bin/env python3
"""Chrome CDP screenshot via pure-Python WebSocket."""
import subprocess, time, socket, base64, struct, json, urllib.request, os, sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT   = 9278

def ws_connect(path):
    s = socket.socket()
    s.connect(("localhost", PORT))
    s.settimeout(60)
    key = base64.b64encode(b"ConnorPortfolio0").decode()
    s.send((
        f"GET {path} HTTP/1.1\r\nHost: localhost:{PORT}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(512)
    return s

MASK = b"\x37\xa8\x3f\x09"

def ws_send(s, obj):
    data = json.dumps(obj).encode()
    frame = bytearray([0x81])
    if len(data) < 126:
        frame.append(0x80 | len(data))
    elif len(data) < 65536:
        frame.append(0xFE); frame += struct.pack(">H", len(data))
    else:
        frame.append(0xFF); frame += struct.pack(">Q", len(data))
    frame += MASK
    frame += bytes(b ^ MASK[i % 4] for i, b in enumerate(data))
    s.sendall(bytes(frame))

def ws_recv(s):
    def read_exact(n):
        buf = b""
        while len(buf) < n:
            c = s.recv(min(131072, n - len(buf)))
            if not c:
                raise ConnectionError("closed")
            buf += c
        return buf
    full = b""
    while True:
        h = read_exact(2)
        fin    = (h[0] & 0x80) != 0
        masked = (h[1] & 0x80) != 0
        length = h[1] & 0x7f
        if length == 126: length = struct.unpack(">H", read_exact(2))[0]
        elif length == 127: length = struct.unpack(">Q", read_exact(8))[0]
        if masked:
            msk = read_exact(4)
            raw = read_exact(length)
            full += bytes(b ^ msk[i % 4] for i, b in enumerate(raw))
        else:
            full += read_exact(length)
        if fin:
            break
    return json.loads(full.decode())

def cdp(s, method, params=None, cmd_id=1):
    ws_send(s, {"id": cmd_id, "method": method, "params": params or {}})
    for _ in range(60):  # up to 60 messages before timeout
        msg = ws_recv(s)
        if msg.get("id") == cmd_id:
            return msg.get("result", {})
    raise TimeoutError(f"No response for {method}")

def take_screenshot(url, output):
    pkill = subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"],
                           capture_output=True)
    time.sleep(0.5)

    chrome = subprocess.Popen([
        CHROME, "--headless", f"--remote-debugging-port={PORT}",
        "--window-size=1440,900", "--disable-gpu", "--no-sandbox",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        time.sleep(2.5)
        tabs = json.loads(urllib.request.urlopen(f"http://localhost:{PORT}/json/list").read())
        tab  = next((t for t in tabs if "newtab" in t.get("url", "") or "about:blank" in t.get("url", "")), tabs[-1])
        path = tab["webSocketDebuggerUrl"].split(f"localhost:{PORT}")[1]
        s    = ws_connect(path)

        # Navigate
        cdp(s, "Page.navigate", {"url": url}, cmd_id=1)
        time.sleep(2.5)

        # Reveal all animated elements
        cdp(s, "Runtime.evaluate", {
            "expression": "document.querySelectorAll('.reveal').forEach(e=>e.classList.add('in'));"
        }, cmd_id=2)
        time.sleep(0.4)

        # Screenshot
        result = cdp(s, "Page.captureScreenshot", {
            "format": "png", "quality": 90, "captureBeyondViewport": False
        }, cmd_id=3)
        s.close()

        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        with open(output, "wb") as f:
            f.write(base64.b64decode(result["data"]))
        print(f"Saved: {output}")
    finally:
        chrome.kill()
        time.sleep(0.3)

if __name__ == "__main__":
    url   = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
    label = sys.argv[2] if len(sys.argv) > 2 else None

    base = "temporary screenshots"
    os.makedirs(base, exist_ok=True)
    i = 1
    while os.path.exists(os.path.join(base, f"screenshot-{i}{'-'+label if label else ''}.png")):
        i += 1
    out = os.path.join(base, f"screenshot-{i}{'-'+label if label else ''}.png")
    take_screenshot(url, out)
