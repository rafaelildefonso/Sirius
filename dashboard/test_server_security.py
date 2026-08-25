"""Integration smoke-test for the new pairing/sync security flow.

Runs against an isolated SIRIUS_DATA_DIR so it never touches the real config.
Run: python dashboard/test_server_security.py
"""
import base64
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate config writes from the real user data BEFORE anything imports
# core.config_loader.
os.environ.setdefault("SIRIUS_DATA_DIR", tempfile.mkdtemp(prefix="sirius-test-"))

from fastapi.testclient import TestClient  # noqa: E402

from dashboard.server import DashboardServer, _derive_key, _encrypt_cbc, _decrypt_cbc  # noqa: E402


def main() -> int:
    ds = DashboardServer()
    client = TestClient(ds.app)
    failures = []

    def check(name: str, cond: bool, extra=""):
        print(f"{'PASS' if cond else 'FAIL'}: {name} {extra}")
        if not cond:
            failures.append(name)

    # -- 1. pair with INVALID key -> 401 -------------------------------------
    r = client.post("/api/device/pair", json={
        "device_id": "dev-1", "device_name": "Teste", "pair_key": "ZZZZZZ",
    })
    check("pair invalid key -> 401", r.status_code == 401, f"(got {r.status_code})")

    # -- 2. pair WITHOUT key -> 409 pending + nonce ---------------------------
    r = client.post("/api/device/pair", json={"device_id": "dev-manual"})
    body = r.json()
    check("manual pair -> 409 pending_approval",
          r.status_code == 409 and body.get("pending_approval") is True,
          f"(got {r.status_code} {body})")
    nonce = body.get("nonce", "")
    check("nonce returned", bool(nonce))

    # status with WRONG nonce -> 401
    r = client.get("/api/device/pair/status", params={"device_id": "dev-manual", "nonce": "wrong"})
    check("pair/status wrong nonce -> 401", r.status_code == 401, f"(got {r.status_code})")
    # status with RIGHT nonce -> pending
    r = client.get("/api/device/pair/status", params={"device_id": "dev-manual", "nonce": nonce})
    check("pair/status right nonce -> pending",
          r.status_code == 200 and r.json().get("status") == "pending")

    # approve via shared method -> trusted
    r = client.post("/api/device/pair/approve", json={
        "device_id": "dev-manual", "approve": True}, headers={"Authorization": "Bearer x"})
    check("approve without valid session -> rejected by _auth", r.status_code == 401,
          f"(got {r.status_code})")

    # approve directly through the core method
    resp = __import__("asyncio").get_event_loop().run_until_complete(ds.approve_pairing("dev-manual", True))
    check("approve_pairing ok", resp.status_code == 200)
    man_info = ds._trusted_devices["dev-manual"]
    check("manual device has session_key+token", bool(man_info.get("session_key")) and bool(man_info.get("token")))
    man_token = man_info["token"]
    man_sk = man_info["session_key"]

    # -- 3. pair with VALID key -> auto-approved ------------------------------
    key = ds.new_key(expiry_secs=120)
    r = client.post("/api/device/pair", json={
        "device_id": "dev-qr", "device_name": "QR Fone", "model": "Pixel", "pair_key": key,
    })
    body = r.json()
    check("pair valid key -> 200 paired", r.status_code == 200 and body.get("paired") is True)
    qr_token = body.get("device_token", "")
    sk = body.get("session_key", "")
    check("session_key == consumed key", sk == key)
    check("key consumed one-time",
          key not in ds._pending_keys)

    headers = {"X-Device-ID": "dev-qr", "Authorization": f"Bearer {qr_token}"}

    # -- 4. sync/batch ENCRYPTED item -> processed ----------------------------
    aes = _derive_key(sk)
    payload = {"text": "ligue as luzes", "timestamp": "2026-01-01T00:00:00"}
    enc_payload = _encrypt_cbc(aes, json.dumps(payload))
    r = client.post("/api/sync/batch", headers=headers, json={
        "items": [{"client_id": "c1", "type": "command", "payload": enc_payload, "enc": True}],
    })
    body = r.json()
    check("encrypted batch processed",
          r.status_code == 200 and body["results"][0]["status"] == "processed", f"({body})")
    got = ds._command_queue.get_nowait()
    check("command decrypted into queue", got == "ligue as luzes", f"(got {got!r})")

    # tampered ciphertext -> failed
    bad = base64.b64encode(b"\x00" * 48).decode()
    r = client.post("/api/sync/batch", headers=headers, json={
        "items": [{"client_id": "c2", "type": "command", "payload": bad, "enc": True}],
    })
    check("tampered payload -> failed",
          r.json()["results"][0]["status"] == "failed")

    # plaintext still accepted (legacy compat)
    r = client.post("/api/sync/batch", headers=headers, json={
        "items": [{"client_id": "c3", "type": "command", "payload": {"text": "plain"}}],
    })
    check("plaintext batch accepted",
          r.json()["results"][0]["status"] == "processed")

    # -- 5. push PC->phone + pull encrypted ------------------------------------
    n = ds.queue_phone_command({"text": "ola do PC"})
    check("queue_phone_command queued for devices", n >= 1, f"(n={n})")
    r = client.get("/api/device/sync/pull", headers=headers)
    body = r.json()
    check("pull enc flag", body.get("enc") is True)
    cmds = body.get("commands", [])
    check("pull command encrypted wrapper",
          len(cmds) == 1 and cmds[0].get("enc") is True)
    dec = json.loads(_decrypt_cbc(aes, cmds[0]["payload"]))
    check("pull decrypts to original text", dec.get("text") == "ola do PC", f"({dec})")
    check("pull drained queue", ds._pending_phone_commands.get("dev-qr") == [])

    # -- 6. auth enforcement ---------------------------------------------------
    r = client.post("/api/sync/batch", headers={
        "X-Device-ID": "dev-qr", "Authorization": "Bearer bogus"}, json={"items": []})
    check("bad token -> 401", r.status_code == 401)

    # wrong device pairing token from other device id mismatch
    r = client.post("/api/sync/batch", headers={
        "X-Device-ID": "dev-other", "Authorization": f"Bearer {man_token}"}, json={"items": []})
    check("token/device_id mismatch -> 401", r.status_code == 401)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
