"""
dashboard/server.py — Local HTTP Dashboard for phone remote control

Plain HTTP on port 8000 (no SSL warnings, no firewall issues).
Optionally uses FastAPI/uvicorn if installed; falls back to Python's built-in http.server.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import socket
import string
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = 8000
MAX_UPLOAD_MB = 500


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "JARVIS Uploads",
        Path.home() / "Documents" / "JARVIS Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# -- AES-256-CBC ---------------------------------------------------------------
_AES_SALT = b'SIRIUS-DASHBOARD-v1'


def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey||salt) -> 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] || ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# -- CryptoJS (auto-download once, served locally) -----------------------------
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI -> sudo -n -> prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # -- Windows --------------------------------------------------------------
    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"SIRIUS Dashboard Port {port}"
        prog_rule = "SIRIUS Dashboard Python"
        py_exe    = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="sirius_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # -- Try running directly (succeeds when already admin) ----------------
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # -- ShellExecuteW: native UAC elevation (most reliable on Windows) ----
        # ShellExecuteW with verb "runas" always shows the UAC dialog regardless
        # of UAC level settings. Non-blocking — uvicorn is already running.
        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,       # hwnd  (no parent window)
                "runas",    # verb  (request elevation)
                bat_path,   # file  (our .bat)
                None,       # params
                None,       # working dir
                0,          # SW_HIDE (run without a visible cmd window)
            )
            if int(ret) > 32:
                # ShellExecuteW returns immediately; bat finishes in ~1 second.
                # Sleep briefly so the rules are in place before the first retry.
                time.sleep(2)
                print(f"[Dashboard] Network setup complete — port {port} is open.")
                print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                print("[Dashboard] Phone connections may fail until SIRIUS is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # -- macOS -----------------------------------------------------------------
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # -- Linux -----------------------------------------------------------------
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")


_ensure_crypto_js()


# -- helpers -------------------------------------------------------------------

def _detect_lan_ip() -> str:
    """Return the first non-loopback IPv4 address.
    Works completely offline; falls back to "127.0.0.1" only if no suitable address is found.
    """
    print("[DEBUG _detect_lan_ip] Starting LAN IP detection...")
    # Try UDP-socket trick – fast when a network route exists.
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            addr = s.getsockname()[0]
            s.close()
            if not addr.startswith("127."):
                print(f"[DEBUG _detect_lan_ip] Found via UDP probe {probe}: {addr}")
                return addr
        except Exception as e:
            print(f"[DEBUG _detect_lan_ip] UDP probe {probe} failed: {e}")

    # Hostname resolution – may return a loopback on some systems.
    try:
        addr = socket.gethostbyname(socket.gethostname())
        if not addr.startswith("127."):
            print(f"[DEBUG _detect_lan_ip] Found via hostname: {addr}")
            return addr
        else:
            print(f"[DEBUG _detect_lan_ip] Hostname resolved to loopback: {addr}")
    except Exception as e:
        print(f"[DEBUG _detect_lan_ip] Hostname resolution failed: {e}")

    # Enumerate all interfaces – guarantees a result on most OSes.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127.") and not addr.startswith("169.254."):
                print(f"[DEBUG _detect_lan_ip] Found via interface enumeration: {addr}")
                return addr
    except Exception as e:
        print(f"[DEBUG _detect_lan_ip] Interface enumeration failed: {e}")

    print("[DEBUG _detect_lan_ip] No LAN IP found, falling back to 127.0.0.1")
    return "127.0.0.1"

# Backwards-compatible alias used by existing code.
def _local_ip() -> str:
    return _detect_lan_ip()


# Embedded HTML content to avoid file I/O issues with PyInstaller + Windows Defender.
# Regenerate by reading dashboard/static/login.html and app.html.
_LOGIN_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>SIRIUS</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:     #07090f;
      --card:   rgba(255,255,255,0.04);
      --border: rgba(255,255,255,0.08);
      --accent: #6366f1;
      --adim:   rgba(99,102,241,0.15);
      --text:   #dde3ed;
      --muted:  #5e6a7e;
    }
    html, body {
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .card {
      width: 340px;
      padding: 44px 36px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 22px;
      text-align: center;
    }
    .logo { font-size: 28px; font-weight: 700; letter-spacing: 10px; margin-bottom: 6px; }
    .logo em { color: var(--accent); font-style: normal; }
    .sub { font-size: 11px; color: var(--muted); letter-spacing: 3px; text-transform: uppercase; margin-bottom: 10px; }
    .hint { font-size: 12px; color: var(--muted); line-height: 1.55; margin-bottom: 28px; }
    .key-wrap { position: relative; margin-bottom: 16px; }
    .key-input {
      width: 100%; padding: 18px 14px; background: rgba(255,255,255,0.05);
      border: 1.5px solid var(--border); border-radius: 14px; color: var(--text);
      font-size: 30px; font-weight: 700; font-family: 'Courier New', monospace;
      text-align: center; letter-spacing: 10px; text-transform: uppercase;
      outline: none; transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
      caret-color: var(--accent);
    }
    .key-input::placeholder { color: rgba(94,106,126,0.5); letter-spacing: 6px; font-size: 20px; }
    .key-input:focus { border-color: var(--accent); background: var(--adim); box-shadow: 0 0 0 3px rgba(99,102,241,0.12); }
    .err { font-size: 12px; color: #f87171; min-height: 18px; margin-bottom: 14px; }
    .btn { width: 100%; padding: 14px; background: var(--accent); color: #fff; font-size: 12px; font-weight: 700; letter-spacing: 3px; border: none; border-radius: 12px; cursor: pointer; transition: opacity 0.15s, transform 0.1s; }
    .btn:hover  { opacity: 0.88; }
    .btn:active { transform: scale(0.98); }
    @keyframes shake { 0%,100% { transform: translateX(0); } 20%,60% { transform: translateX(-7px); } 40%,80% { transform: translateX(7px); } }
    .shake { animation: shake 0.35s ease; }
    .voice-note { font-size: 10px; color: var(--muted); margin-top: 20px; line-height: 1.6; text-align: left; }
    .voice-note code { background: rgba(255,255,255,0.07); padding: 1px 4px; border-radius: 3px; font-family: 'Courier New', monospace; font-size: 9px; }
    #reconnecting { display: none; color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  </style>
</head>
<body>
  <div class="card" id="card">
    <div class="logo"><em>S</em>IRIUS</div>
    <div class="sub">Remote Access</div>
    <p id="reconnecting">Reconnecting…</p>
    <p class="hint">Press <strong style="color:var(--text)">Remote Control</strong> in the SIRIUS desktop app to get a QR code or session key.</p>
    <div class="key-wrap">
      <input class="key-input" id="key" type="text" maxlength="6"
             autocomplete="off" autocorrect="off" spellcheck="false"
             placeholder="· · · · · ·">
    </div>
    <div class="err" id="err"></div>
    <button class="btn" onclick="doLogin()">CONNECT</button>
    <p class="voice-note">🎤 <strong style="color:var(--text)">Voice commands:</strong> open <code>chrome://flags</code> on your phone, search <code>Insecure origins treated as secure</code>, add your SIRIUS URL, tap Relaunch.</p>
  </div>
  <script>
    (async function() {
      const devTok = localStorage.getItem('sirius_device_token');
      if (!devTok) return;
      document.getElementById('reconnecting').style.display = 'block';
      try {
        const r = await fetch('/api/device-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_token: devTok }) });
        const d = await r.json();
        if (d.ok && d.token) { sessionStorage.setItem('sirius_key', d.key); sessionStorage.setItem('sirius_token', d.token); location.replace('/'); return; }
      } catch (_) {}
      localStorage.removeItem('jarvis_device_token');
      document.getElementById('reconnecting').style.display = 'none';
    })();
    const inp = document.getElementById('key'); inp.focus();
    inp.addEventListener('input', () => { inp.value = inp.value.toUpperCase().replace(/[^A-Z2-9]/g, ''); if (inp.value.length === 6) doLogin(); });
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
    async function doLogin() {
      const key = inp.value.trim();
      if (key.length < 6) { shake(); return; }
      let data;
      try { const r = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin: key }) }); data = await r.json(); }
      catch (e) { document.getElementById('err').textContent = 'Connection error'; shake(); return; }
      if (data.ok && data.token) { sessionStorage.setItem('sirius_key', key); sessionStorage.setItem('jarvis_token', data.token); location.href = '/'; }
      else { inp.value = ''; inp.focus(); document.getElementById('err').textContent = 'Invalid or expired key'; shake(); }
    }
    function shake() { const c = document.getElementById('card'); c.classList.remove('shake'); void c.offsetWidth; c.classList.add('shake'); }
  </script>
</body>
</html>"""

_APP_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SIRIUS Dashboard</title>
  <script src="/static/crypto.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:      #07090f;
      --surface: rgba(255,255,255,0.04);
      --border:  rgba(255,255,255,0.07);
      --accent:  #6366f1;
      --adim:    rgba(99,102,241,0.14);
      --text:    #dde3ed;
      --muted:   #5e6a7e;
      --green:   #22c55e;
      --gdim:    rgba(34,197,94,0.14);
    }
    html, body { height: 100%; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; display: flex; flex-direction: column; overflow: hidden; }
    header { flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--border); background: rgba(7,9,15,0.95); }
    .logo { font-size: 15px; font-weight: 700; letter-spacing: 6px; }
    .logo em { color: var(--accent); font-style: normal; }
    .pill { display: flex; align-items: center; gap: 6px; padding: 4px 11px; border-radius: 99px; background: var(--surface); border: 1px solid var(--border); font-size: 10px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted); transition: all 0.3s; }
    .pill.on { background: var(--gdim); border-color: rgba(34,197,94,0.3); color: var(--green); }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); transition: background 0.3s; }
    .pill.on .dot { background: var(--green); animation: blink 2s infinite; }
    @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.4} }
    .spacer { flex: 1; }
    .enc-badge { font-size: 9px; font-weight: 700; letter-spacing: 1.5px; padding: 3px 8px; border-radius: 4px; display: none; }
    .enc-badge.on  { display: block; background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.25); color: var(--green); }
    .enc-badge.off { display: block; background: rgba(255,100,100,0.08); border: 1px solid rgba(255,100,100,0.2); color: #f87171; }
    .url { font-size: 10px; font-family: monospace; color: var(--muted); padding: 4px 9px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }
    main { flex: 1; overflow-y: auto; padding: 14px 16px 8px; display: flex; flex-direction: column; gap: 10px; }
    main::-webkit-scrollbar { width: 3px; }
    main::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    .msg { max-width: 82%; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.55; animation: pop 0.18s ease; }
    @keyframes pop { from { opacity:0; transform:translateY(4px); } }
    .msg-j   { align-self:flex-start; background:var(--adim);   border:1px solid rgba(99,102,241,0.18); border-bottom-left-radius:4px; }
    .msg-u   { align-self:flex-end;   background:var(--surface); border:1px solid var(--border);        border-bottom-right-radius:4px; }
    .msg-sys { align-self:center; font-size:11px; color:var(--muted); padding:2px 0; background:transparent; border:none; letter-spacing:0.3px; }
    .lbl { font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; opacity:0.45; margin-bottom:4px; }
    .msg-j .lbl { color:var(--accent); }
    .msg-u .lbl { color:var(--muted); text-align:right; }
    .msg-file { align-self: flex-end; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; border-bottom-right-radius: 4px; padding: 11px 14px; display: flex; align-items: center; gap: 12px; max-width: 82%; animation: pop 0.18s ease; }
    .fc-icon { font-size: 26px; flex-shrink: 0; }
    .fc-meta { flex: 1; min-width: 0; }
    .fc-lbl  { font-size:9px; font-weight:700; letter-spacing:2px; text-transform:uppercase; opacity:0.45; color:var(--muted); margin-bottom:4px; }
    .fc-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .fc-size { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .fc-bar-wrap { height: 3px; background: var(--border); border-radius: 2px; margin-top: 7px; overflow: hidden; }
    .fc-bar { height: 100%; width: 0%; background: var(--accent); border-radius: 2px; transition: width 0.12s linear; }
    .fc-status { font-size: 10px; font-weight: 700; letter-spacing: 1px; flex-shrink: 0; color: var(--muted); }
    .fc-status.done { color: var(--green); }
    .fc-status.err  { color: #f87171; }
    .fc-dl { display:block; margin-top:6px; font-size:11px; color:var(--accent); text-decoration:none; font-weight:600; }
    .fc-dl:hover { opacity: 0.8; }
    footer { flex-shrink:0; padding:10px 14px; border-top:1px solid var(--border); background:rgba(7,9,15,0.95); display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    footer > #inp { min-width: 120px; }
    footer > #inp, footer > .btn, footer > .btn-attach { flex-shrink: 1; }
    #inp { flex:1; padding:11px 14px; background:var(--surface); border:1.5px solid var(--border); border-radius:12px; color:var(--text); font-size:14px; outline:none; transition:border-color 0.15s; }
    #inp:focus { border-color: var(--accent); }
    #inp::placeholder { color: var(--muted); }
    .btn { padding:11px 15px; border:none; border-radius:12px; font-size:11px; font-weight:700; letter-spacing:1.5px; cursor:pointer; transition:opacity 0.15s,transform 0.1s; }
    .btn:active { transform: scale(0.96); }
    .btn:hover  { opacity: 0.82; }
    .btn-send { background: var(--accent); color: #fff; }
    .btn-wake { background:var(--surface); border:1px solid var(--border); color:var(--muted); display:none; }
    .btn-wake.show { display:block; color:var(--green); border-color:rgba(34,197,94,0.35); }
    .btn-attach { background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 11px 13px; font-size: 16px; line-height: 1; border-radius: 12px; cursor: pointer; transition: opacity 0.15s, transform 0.1s; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .btn-attach:hover  { opacity: 0.82; border-color: var(--accent); color: var(--accent); }
    .btn-attach:active { transform: scale(0.96); }
    #mic-btn { background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 11px 13px; font-size: 16px; line-height: 1; border-radius: 12px; cursor: pointer; transition: opacity 0.15s, transform 0.1s, background 0.2s, border-color 0.2s; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    #mic-btn:hover  { opacity: 0.82; border-color: var(--accent); color: var(--accent); }
    #mic-btn:active { transform: scale(0.96); }
    #mic-btn.recording { background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.45); color: #ef4444; animation: mic-pulse 1s ease-in-out infinite; }
    #mic-btn.unsupported { opacity: 0.3; cursor: not-allowed; }
    @keyframes mic-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.65;transform:scale(0.97)} }
    #toast { position:fixed; top:66px; left:50%; transform:translateX(-50%) translateY(-8px); background:rgba(34,197,94,0.16); border:1px solid rgba(34,197,94,0.4); color:var(--green); font-size:12px; font-weight:700; letter-spacing:1px; padding:7px 18px; border-radius:99px; opacity:0; transition:opacity 0.22s,transform 0.22s; pointer-events:none; white-space:nowrap; }
    #toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
  </style>
</head>
<body>
  <div id="toast"></div>
  <header>
    <div class="logo"><em>S</em>IRIUS</div>
    <div class="pill" id="pill"><span class="dot"></span><span id="st">Connecting</span></div>
    <div class="enc-badge" id="enc">AES-256</div>
    <div class="spacer"></div>
    <div class="url">__IP__:__PORT__</div>
  </header>
  <main id="feed"></main>
  <footer>
    <input id="inp" placeholder="Send a command to SIRIUS…" autocomplete="off">
    <label class="btn-attach" for="file-inp" title="Send file">📎</label>
    <input type="file" id="file-inp" multiple accept="*/*" style="display:none">
    <button id="mic-btn" onclick="doMic()" title="Voice command">🎤</button>
    <button class="btn btn-wake" id="wake" onclick="doWake()">WAKE</button>
    <button class="btn btn-send" onclick="doSend()">SEND</button>
  </footer>
  <script>
    const _authToken  = sessionStorage.getItem('sirius_token');
    const _sessionKey = sessionStorage.getItem('sirius_key');
    if (!_authToken) { location.replace('/login'); }
    function _authHeader() { return { 'Authorization': 'Bearer ' + _authToken }; }
    function _authFetch(url, opts) { opts = opts || {}; opts.headers = Object.assign({}, opts.headers, _authHeader()); return fetch(url, opts); }
    const _AES_SALT = 'SIRIUS-DASHBOARD-v1';
    let _aesKey = null;
    function _initCrypto(key) { if (typeof CryptoJS === 'undefined') return false; _aesKey = CryptoJS.SHA256(key + _AES_SALT); return true; }
    function _encrypt(plaintext) {
      if (!_aesKey || typeof CryptoJS === 'undefined') return null;
      try {
        const iv  = CryptoJS.lib.WordArray.random(16);
        const enc = CryptoJS.AES.encrypt(CryptoJS.enc.Utf8.parse(plaintext), _aesKey, { iv, mode: CryptoJS.mode.CBC, padding: CryptoJS.pad.Pkcs7 });
        const ivHex = iv.toString(CryptoJS.enc.Hex);
        const ctHex = enc.ciphertext.toString(CryptoJS.enc.Hex);
        const hex = ivHex + ctHex;
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
        return btoa(String.fromCharCode.apply(null, bytes));
      } catch(e) { return null; }
    }
    const _encReady = _sessionKey ? _initCrypto(_sessionKey) : false;
    const encBadge  = document.getElementById('enc');
    if (_encReady) { encBadge.className = 'enc-badge on'; }
    else           { encBadge.className = 'enc-badge off'; encBadge.textContent = 'NO ENC'; }
    const feed  = document.getElementById('feed');
    const pill  = document.getElementById('pill');
    const stTxt = document.getElementById('st');
    const wake  = document.getElementById('wake');
    const _wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
    const _wsUrl   = _wsProto + '://' + location.host + '/ws?token=' + encodeURIComponent(_authToken);
    const ws = new WebSocket(_wsUrl);
    ws.onopen    = function() { sys('Remote session active.'); toast('Connected to SIRIUS'); };
    ws.onclose   = function() { sys('Connection lost — refresh to reconnect.'); };
    ws.onerror   = function() { sys('Connection error.'); };
    ws.onmessage = function(e) {
      var m = JSON.parse(e.data);
      if (m.type === 'log')           append(m.speaker, m.text);
      if (m.type === 'status')        setStatus(m.state);
      if (m.type === 'wake')          sys('Wake word detected — connecting…');
      if (m.type === 'sys')           sys(m.text);
      if (m.type === 'file_received') _onFileReceived(m);
    };
    function setStatus(s) {
      if (s === 'active') { pill.className = 'pill on'; stTxt.textContent = 'Active'; wake.classList.remove('show'); }
      else { pill.className = 'pill'; stTxt.textContent = 'Sleeping'; wake.classList.add('show'); }
    }
    function append(speaker, text) {
      var d = document.createElement('div');
      if (speaker === 'sirius') { d.className = 'msg msg-j'; d.innerHTML = '<div class="lbl">SIRIUS</div>' + esc(text); }
      else { d.className = 'msg msg-u'; d.innerHTML = '<div class="lbl">You</div>' + esc(text); }
      feed.appendChild(d); feed.scrollTop = feed.scrollHeight;
    }
    function sys(text) { var d = document.createElement('div'); d.className = 'msg msg-sys'; d.textContent = text; feed.appendChild(d); feed.scrollTop = feed.scrollHeight; }
    function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
    function _fileIcon(name) { var ext = (name.split('.').pop() || '').toLowerCase(); if (['jpg','jpeg','png','gif','webp','heic','heif','avif','bmp','svg'].includes(ext)) return '\u{1F5BC}'; if (['mp4','mov','avi','mkv','webm','m4v','3gp'].includes(ext)) return '\u{1F3AC}'; if (['mp3','m4a','wav','flac','aac','ogg','opus'].includes(ext)) return '\u{1F3B5}'; if (['pdf'].includes(ext)) return '\u{1F4CB}'; if (['doc','docx','txt','md','rtf','odt'].includes(ext)) return '\u{1F4DD}'; if (['xls','xlsx','csv','ods'].includes(ext)) return '\u{1F4CA}'; if (['ppt','pptx','odp'].includes(ext)) return '\u{1F4D1}'; if (['zip','rar','7z','tar','gz','bz2','xz'].includes(ext)) return '\u{1F4E6}'; if (['apk','exe','dmg','deb','rpm','msi'].includes(ext)) return '\u{2699}'; return '\u{1F4CE}'; }
    function _fmtSize(bytes) { if (bytes < 1024) return bytes + ' B'; if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'; if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'; return (bytes / (1024*1024*1024)).toFixed(2) + ' GB'; }
    function _uploadFile(file) {
      var id = 'fc_' + Date.now() + '_' + Math.random().toString(36).slice(2);
      var card = document.createElement('div');
      card.className = 'msg-file'; card.id = id;
      card.innerHTML = '<div class="fc-icon">' + _fileIcon(file.name) + '</div><div class="fc-meta"><div class="fc-lbl">Sending</div><div class="fc-name">' + esc(file.name) + '</div><div class="fc-size">' + _fmtSize(file.size) + '</div><div class="fc-bar-wrap"><div class="fc-bar" id="' + id + '_bar"></div></div></div><div class="fc-status" id="' + id + '_st">0%</div>';
      feed.appendChild(card); feed.scrollTop = feed.scrollHeight;
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/upload');
      xhr.setRequestHeader('Authorization', 'Bearer ' + _authToken);
      xhr.upload.onprogress = function(e) { if (!e.lengthComputable) return; var pct = Math.round(e.loaded / e.total * 100); var bar = document.getElementById(id + '_bar'); var st  = document.getElementById(id + '_st'); if (bar) bar.style.width = pct + '%'; if (st) st.textContent = pct + '%'; };
      xhr.onload = function() {
        var bar = document.getElementById(id + '_bar'); var st = document.getElementById(id + '_st'); var meta = card.querySelector('.fc-meta'); var lbl = card.querySelector('.fc-lbl');
        if (xhr.status === 200) { var savedName = file.name; try { savedName = JSON.parse(xhr.responseText).name || file.name; } catch(e) {} var dlUrl = '/uploads/' + encodeURIComponent(savedName) + '?token=' + encodeURIComponent(_authToken); if (bar) { bar.style.width = '100%'; bar.style.background = 'var(--green)'; } if (st) { st.textContent = '\u2713'; st.className = 'fc-status done'; } if (lbl) lbl.textContent = 'Sent'; if (meta) meta.insertAdjacentHTML('beforeend', '<a class="fc-dl" href="' + dlUrl + '" download="' + esc(savedName) + '">\u2B07 Download back</a>'); toast('File sent!'); }
        else { var errMsg = 'Upload failed'; try { errMsg = JSON.parse(xhr.responseText).error || errMsg; } catch(e) {} if (bar) bar.style.background = '#f87171'; if (st) { st.textContent = 'ERR'; st.className = 'fc-status err'; } if (lbl) lbl.textContent = errMsg; }
      };
      xhr.onerror = function() { var st = document.getElementById(id + '_st'); var lbl = card.querySelector('.fc-lbl'); if (st) { st.textContent = 'ERR'; st.className = 'fc-status err'; } if (lbl) lbl.textContent = 'Connection error'; };
      var fd = new FormData(); fd.append('file', file); xhr.send(fd);
    }
    function _onFileReceived(m) {
      var dlUrl = '/uploads/' + encodeURIComponent(m.name) + '?token=' + encodeURIComponent(_authToken);
      var card = document.createElement('div');
      card.className = 'msg-file';
      card.innerHTML = '<div class="fc-icon">' + _fileIcon(m.name) + '</div><div class="fc-meta"><div class="fc-lbl">Received</div><div class="fc-name">' + esc(m.name) + '</div><div class="fc-size">' + _fmtSize(m.size) + '</div><a class="fc-dl" href="' + dlUrl + '" download="' + esc(m.name) + '">\u2B07 Download</a></div><div class="fc-status done">\u2713</div>';
      feed.appendChild(card); feed.scrollTop = feed.scrollHeight; toast('File received on computer!');
    }
    document.getElementById('file-inp').addEventListener('change', function() { Array.from(this.files).forEach(_uploadFile); this.value = ''; });
    function doSend() { var inp = document.getElementById('inp'); var txt = inp.value.trim(); if (!txt) return; inp.value = ''; append('user', txt); var enc = _encrypt(txt); var body = enc ? { enc: enc } : { text: txt }; _authFetch('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
    function doWake() { sys('Sending wake signal\u2026'); _authFetch('/api/wake', { method: 'POST' }); }
    document.getElementById('inp').addEventListener('keydown', function(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); } });
    var _toastTimer;
    function toast(msg) { var t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(_toastTimer); _toastTimer = setTimeout(function() { t.classList.remove('show'); }, 2800); }
    var micBtn = document.getElementById('mic-btn');
    var _voiceWs = null, _audioCtx = null, _micStm = null, _audioNd = null;
    function _micIdle() { micBtn.innerHTML = '\u{1F3A4}'; micBtn.title = 'Voice \u2014 tap to speak'; micBtn.classList.remove('recording'); }
    function _f32toPcm16(f32, srcRate) {
      var s = f32;
      if (srcRate !== 16000) { var ratio = srcRate / 16000; var len = Math.round(f32.length / ratio); s = new Float32Array(len); for (var i = 0; i < len; i++) s[i] = f32[Math.min(Math.round(i * ratio), f32.length - 1)]; }
      var out = new Int16Array(s.length);
      for (var i = 0; i < s.length; i++) out[i] = Math.max(-32768, Math.min(32767, Math.round(s[i] * 32768)));
      return out.buffer;
    }
    function _showVoiceSetup() {
      if (document.getElementById('voice-setup')) return;
      var origin = location.origin;
      var card = document.createElement('div');
      card.id = 'voice-setup';
      card.style.cssText = 'align-self:stretch;background:rgba(99,102,241,0.07);border:1px solid rgba(99,102,241,0.22);border-radius:14px;padding:16px 18px;font-size:13px;line-height:1.8;animation:pop 0.18s ease';
      card.innerHTML = '<div style="font-weight:700;color:#818cf8;letter-spacing:.5px;margin-bottom:10px">\u{1F3A4} One-time voice setup</div><ol style="padding-left:18px;color:#8899aa;margin:0;display:flex;flex-direction:column;gap:4px"><li>Open a new tab \u2192 go to <span style="background:rgba(255,255,255,0.07);padding:1px 6px;border-radius:4px;font-family:monospace;font-size:12px">chrome://flags</span></li><li>Search: <strong style="color:#dde3ed">Insecure origins treated as secure</strong></li><li>Paste this URL into the box:<br><span id="flags-url" style="background:rgba(255,255,255,0.07);padding:2px 8px;border-radius:4px;font-family:monospace;font-size:11px;user-select:all;cursor:pointer">' + esc(origin) + '</span></li><li>Set to <strong style="color:#22c55e">Enabled</strong> \u2192 tap <strong style="color:#dde3ed">Relaunch</strong></li><li>Return here and tap \u{1F3A4}</li></ol>';
      feed.appendChild(card); feed.scrollTop = feed.scrollHeight;
      card.querySelector('#flags-url').addEventListener('click', function() { navigator.clipboard.writeText(origin).then(function() { toast('URL copied!'); }).catch(function() {}); });
    }
    async function doMic() {
      if (_voiceWs) { _stopVoice(); return; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { _showVoiceSetup(); return; }
      var stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
      catch (e) { sys(e.name === 'NotAllowedError' ? 'Microphone denied \u2014 tap the address bar lock and allow microphone.' : 'Mic error: ' + e.message); return; }
      var ctx;
      try { ctx = new AudioContext({ sampleRate: 16000 }); }
      catch (_) { ctx = new AudioContext(); }
      if (ctx.state === 'suspended') await ctx.resume();
      var wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
      var ws = new WebSocket(wsProto + '://' + location.host + '/ws/phone-audio?token=' + encodeURIComponent(_authToken));
      ws.binaryType = 'arraybuffer';
      ws.onopen = async function() {
        var rate = ctx.sampleRate;
        var src = ctx.createMediaStreamSource(stream);
        var wCode = 'class J extends AudioWorkletProcessor{process(i){const c=i[0]?.[0];if(c)this.port.postMessage(c.slice());return true}}registerProcessor("j",J);';
        try {
          var burl = URL.createObjectURL(new Blob([wCode], { type: 'application/javascript' }));
          await ctx.audioWorklet.addModule(burl);
          URL.revokeObjectURL(burl);
          var nd = new AudioWorkletNode(ctx, 'j');
          var _pbuf = [], _plen = 0;
          nd.port.onmessage = function(e) {
            var chunk = new Int16Array(_f32toPcm16(e.data, rate));
            _pbuf.push(chunk); _plen += chunk.length;
            if (_plen >= 1024) { var out = new Int16Array(_plen); var off = 0; for (var c of _pbuf) { out.set(c, off); off += c.length; } if (ws.readyState === 1) ws.send(out.buffer); _pbuf = []; _plen = 0; }
          };
          src.connect(nd);
          _audioNd = nd;
        } catch (_) {
          var sp = ctx.createScriptProcessor(4096, 1, 1);
          sp.onaudioprocess = function(e) { if (ws.readyState === 1) ws.send(_f32toPcm16(e.inputBuffer.getChannelData(0), rate)); };
          src.connect(sp); sp.connect(ctx.destination);
          _audioNd = sp;
        }
        micBtn.innerHTML = '\u23F9'; micBtn.title = 'Tap to stop'; micBtn.classList.add('recording');
        sys('Voice live \u2014 speak now'); toast('\u{1F3A4} Live');
      };
      ws.onclose = function() { _stopVoice(); };
      ws.onerror = function() { sys('Voice connection failed.'); _stopVoice(); };
      _voiceWs = ws; _audioCtx = ctx; _micStm = stream;
    }
    function _stopVoice() {
      if (_audioNd)  { try { _audioNd.disconnect(); } catch(_) {} _audioNd = null; }
      if (_audioCtx) { try { _audioCtx.close(); } catch(_) {} _audioCtx = null; }
      if (_micStm)   { _micStm.getTracks().forEach(function(t) { t.stop(); }); _micStm = null; }
      if (_voiceWs)  { var w = _voiceWs; _voiceWs = null; if (w.readyState < 2) w.close(); }
      _micIdle();
    }
  </script>
</body>
</html>"""


def _read(name: str) -> str:
    """Return dashboard HTML. Prefers file read (dev mode), falls back to embedded constants."""
    if name == "login.html":
        return _LOGIN_HTML
    if name == "app.html":
        return _APP_HTML
    return "<!DOCTYPE html><html><body style='background:#07090f;color:#dde3ed;font-family:sans-serif'><h1>SIRIUS</h1><p>Dashboard loading...</p></body></html>"


# -- DashboardServer -----------------------------------------------------------

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}   # auth_token -> session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key -> AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}  # device_token -> {session_key}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._ready_event                 = None  # threading.Event set when server is listening
        self._uploads_dir                 = UPLOADS_DIR
        self._login_html                  = None  # lazy-loaded on first request
        self._app_html                    = None  # lazy-loaded on first request
        self.app                          = self._build_app()

    # -- one-time key management -------------------------------------------

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        print(f"[DEBUG DashboardServer.new_key] Key={key}, expires_at={now + expiry_secs}, pending_count={len(self._pending_keys)}")
        print(f"[DEBUG DashboardServer.new_key] All pending keys: {list(self._pending_keys.keys())}")
        return key

    @staticmethod
    @staticmethod
    def _ssl_enabled() -> bool:
        print('[Dashboard] _ssl_enabled called')
        # SSL is intentionally disabled to serve plain HTTP (port 8000) for remote control.
        # Returning False forces both the main server and the alias to use HTTP only.
        return False

    def get_url(self) -> str:
        proto = "https" if self._ssl_enabled() else "http"
        url = f"{proto}://{self._ip}:{PORT}"
        print(f"[DEBUG DashboardServer.get_url] Returning: {url}")
        return url

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            manual = f"{self._ip}:{PORT + 1}"
        else:
            manual = f"{self._ip}:{PORT}"
        print(f"[DEBUG DashboardServer.get_manual_url] Returning: {manual}")
        return manual

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # -- callbacks --------------------------------------------------------

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    # -- broadcast --------------------------------------------------------

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # -- FastAPI app -------------------------------------------------------

    def _build_app(self):
        """Return FastAPI app, or None if fastapi/uvicorn not installed."""
        if not _DEPS_OK:
            return None
        app = FastAPI(docs_url=None, redoc_url=None)

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            if self._login_html is None:
                self._login_html = _read("login.html")
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index():
            if self._app_html is None:
                self._app_html = _read("app.html")
            print(f"[DEBUG /] Serving app.html (IP={self._ip}, PORT={PORT})")
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            print(f"[DEBUG /login] POST request received. pin={entered!r}, pending_keys={list(self._pending_keys.keys())}")
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                print(f"[DEBUG /login] Key {entered} valid, creating session...")
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    print("[DEBUG /login] Calling connect_callback...")
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                print(f"[DEBUG /login] Session created, token={tok[:16]}...")
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok})
            print(f"[DEBUG /login] Key {entered} INVALID or expired. pending_keys={list(self._pending_keys.keys())}")
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            print(f"[DEBUG /auto-login] GET request received. key={key!r}, now={now}")
            print(f"[DEBUG /auto-login] pending_keys={list(self._pending_keys.keys())}")
            if not key:
                print("[DEBUG /auto-login] No key provided in URL")
            elif key not in self._pending_keys:
                print(f"[DEBUG /auto-login] Key {key!r} NOT FOUND in pending_keys")
            elif self._pending_keys[key] <= now:
                print(f"[DEBUG /auto-login] Key {key!r} EXPIRED (expired_at={self._pending_keys[key]}, now={now})")
            else:
                print(f"[DEBUG /auto-login] Key {key!r} VALID, creating session...")

            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                print(f"[DEBUG /auto-login] Returning 'Link Expired' response")
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in SIRIUS to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}
            print(f"[DEBUG /auto-login] Session created. token={tok[:16]}..., dev_tok={dev_tok[:16]}...")

            if self._connect_callback:
                print("[DEBUG /auto-login] Calling connect_callback...")
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            print(f"[DEBUG /auto-login] Redirecting phone to '/' with session...")
            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
sessionStorage.setItem('sirius_token','{tok}');
   sessionStorage.setItem('sirius_key','{key}');
   localStorage.setItem('sirius_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to SIRIUS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # -- Phone mic real-time audio -> Gemini Live --------------------------

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # -- File sharing ------------------------------------------------------

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        # -- Database-backed memory endpoints ------------------------------

        def _get_repo():
            try:
                from persistence.repository import Repository
                return Repository()
            except Exception:
                return None

        @app.get("/api/messages")
        async def get_messages(req: Request, limit: int = 100):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            repo = _get_repo()
            if not repo:
                return JSONResponse({"messages": []})
            try:
                convs = repo.list_conversations(limit=5)
                all_msgs = []
                for c in convs:
                    msgs = repo.get_messages(c["id"], limit=limit // max(len(convs), 1))
                    for m in msgs:
                        m["conversation_title"] = c.get("title", "")
                    all_msgs.extend(msgs)
                all_msgs.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
                return JSONResponse({"messages": all_msgs[:limit]})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/conversations")
        async def get_conversations(req: Request, limit: int = 20):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            repo = _get_repo()
            if not repo:
                return JSONResponse({"conversations": []})
            try:
                convs = repo.list_conversations(limit=limit)
                return JSONResponse({"conversations": convs})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/preferences")
        async def get_preferences(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            repo = _get_repo()
            if not repo:
                return JSONResponse({"preferences": {}})
            try:
                prefs = repo.get_all_preferences()
                return JSONResponse({"preferences": prefs})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/memory/stats")
        async def get_memory_stats(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            repo = _get_repo()
            if not repo:
                return JSONResponse({"stats": {}})
            try:
                stats = repo.get_stats()
                return JSONResponse({"stats": stats})
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            print(f"[DEBUG /ws] WebSocket connection attempt. token={tok[:20]}...")
            if not tok:
                print("[DEBUG /ws] No token provided, closing.")
                await websocket.close(code=4001)
                return
            if tok not in self._tokens:
                print(f"[DEBUG /ws] Token NOT in valid tokens set. tokens_count={len(self._tokens)}")
                await websocket.close(code=4001)
                return
            print(f"[DEBUG /ws] Token VALID, accepting WebSocket. clients before={len(self._clients)}")
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        return app

    # -- serve -------------------------------------------------------------

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:8001 -> Chrome tries https -> self-signed cert warning -> accept once -> done."""
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT + 1)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT + 1, log_level="warning",
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(f"[Dashboard] Manual entry:  {self._ip}:{PORT + 1}  (type in browser, accept cert once)")
        await uvicorn.Server(cfg).serve()

    async def _wait_for_port(self) -> None:
        """Background task: poll port until open, then fire _ready_event."""
        import asyncio
        import socket
        for _ in range(50):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                s.connect(('127.0.0.1', PORT))
                s.close()
                print(f"[Dashboard] Port {PORT} is now LISTENING — dashboard ready.")
                if self._ready_event is not None:
                    self._ready_event.set()
                return
            except Exception:
                pass
            await asyncio.sleep(0.1)
        print(f"[Dashboard] WARNING: Port {PORT} did not become ready within 5s")
        # Fire the event anyway so the caller doesn't hang forever
        if self._ready_event is not None:
            self._ready_event.set()

    async def serve(self) -> None:
        try:
            print(f"[DEBUG DashboardServer.serve] Starting server...")
            print(f"[DEBUG DashboardServer.serve] _DEPS_OK={_DEPS_OK}, app={self.app is not None}")
            print(f"[DEBUG DashboardServer.serve] Detected IP: {self._ip}")
            print(f"[DEBUG DashboardServer.serve] Firewall setup starting in executor...")
            # Firewall setup runs in a thread — uvicorn starts immediately,
            # no waiting for UAC dialogs or subprocess timeouts.
            asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

            if _DEPS_OK and self.app is not None:
                # FastAPI / uvicorn available — use them
                use_ssl  = self._ssl_enabled()
                ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
                ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"

                if use_ssl:
                    asyncio.create_task(self._serve_alias())

                print(f"[DEBUG DashboardServer.serve] Creating uvicorn config on port {PORT}...")
                cfg = uvicorn.Config(
                    self.app, host="0.0.0.0", port=PORT, log_level="warning",
                    **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)} if use_ssl else {}),
                )

                proto = "https" if use_ssl else "http"
                print(f"[Dashboard] {proto}://{self._ip}:{PORT} (FastAPI)")

                # Start port checker before blocking on serve()
                asyncio.create_task(self._wait_for_port())

                print(f"[DEBUG DashboardServer.serve] Calling uvicorn.Server(cfg).serve()...")
                await uvicorn.Server(cfg).serve()
                print(f"[DEBUG DashboardServer.serve] uvicorn serve returned (server stopped)")
                return

            print(f"[DEBUG DashboardServer.serve] FastAPI/uvicorn not available, using fallback server")
            # Fallback: built-in http.server (no deps needed)
            await self.serve_fallback()
        except Exception as e:
            import traceback
            print(f"[Dashboard] SERVE FAILED: {e}")
            traceback.print_exc()
            # Fire the event so callers don't hang forever
            if self._ready_event is not None:
                self._ready_event.set()
            raise

    async def serve_fallback(self):
        """Minimal HTTP server using Python's built-in http.server (zero deps)."""
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading

        pending = self._pending_keys
        tokens  = self._tokens
        tk_keys = self._token_keys
        aes_fn  = self._aes_key
        connect_cb = self._connect_callback
        ip = self._ip

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path
                if path.startswith("/auto-login"):
                    qs = {}
                    if "?" in path:
                        for part in path.split("?", 1)[1].split("&"):
                            if "=" in part:
                                k, v = part.split("=", 1)
                                qs[k] = v
                    key = qs.get("key", "")
                    now = time.time()
                    if key in pending and pending[key] > now:
                        del pending[key]
                        tok = secrets.token_urlsafe(32)
                        tokens.add(tok)
                        tk_keys[tok] = key
                        aes_fn(key)
                        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<script>
sessionStorage.setItem('sirius_token','{tok}');
sessionStorage.setItem('sirius_key','{key}');
localStorage.setItem('sirius_device_token','{tok}');
setTimeout(function(){{location.replace('/')}},400);
</script>
</head><body><p>Connecting to SIRIUS…</p></body></html>"""
                        self._send_html(html)
                        if connect_cb:
                            connect_cb()
                    else:
                        self._send_error("Link Expired",
                            "Press Remote Control in SIRIUS to get a new QR code.")
                elif path == "/":
                    self._send_error("SIRIUS",
                        "Scan the QR code from the SIRIUS app on your phone.")
                elif path.startswith("/login"):
                    self._send_html(_read("login.html"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def _send_html(self, html: str):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(html.encode())

            def _send_error(self, title: str, msg: str):
                html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
h2{{color:#f87171;margin-bottom:12px}}p{{color:#5e6a7e;font-size:14px}}
</style></head><body><div><h2>{title}</h2><p>{msg}</p></div></body></html>"""
                self._send_html(html)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("0.0.0.0", PORT), _Handler)
        print(f"[Dashboard] http://{ip}:{PORT} (built-in server)")
        # Serve in a thread so we don't block the event loop
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            server.shutdown()
