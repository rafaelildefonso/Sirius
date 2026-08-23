"""
SIRIUS plugin — Calorie Counter (webcam vision).

Hold food up to the camera and ask "how many calories is this?" —
SIRIUS switches the frontend to the live camera with an animated scan bar,
photographs the food, analyzes it with Gemini, speaks a short summary
in your language and shows the full nutrition breakdown in the
content panel.

Visuals rely on WsUI's camera stream API (start_camera_stream /
stop_camera_stream). If they're ever missing the plugin still works —
just without the camera view.
"""

import json
import threading
import time

import cv2
import numpy as np

PLUGIN = {
    "name": "calorie_counter",
    "description": (
        "Analyzes FOOD through the WEBCAM and reports calories and nutrition "
        "(carbs, sugar, fiber, protein, fat). Use whenever the user asks about "
        "the calories or nutritional value of food they are physically holding "
        "or showing right now — e.g. 'bu elimdeki tabak kaç kalori', 'how many "
        "calories is this', 'qual a caloria disso'. This tool takes its OWN "
        "camera photo — NEVER use screen_process for food-calorie questions. "
        "Pass the user's exact spoken words in 'query'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "The user's exact request, verbatim, in their own language.",
            }
        },
        "required": ["query"],
    },
}

_MODEL             = "gemini-flash-latest"
_LIVE_SCAN_SECONDS = 1.8     # live preview before the photo is taken
_FPS               = 25
_ANIM_MAX_SECONDS  = 25      # animator safety stop
_SCAN_COLOR        = (255, 190, 40)    # SIRIUS cyan-blue (BGR)
_SCAN_CORE         = (255, 235, 130)   # bright core line (BGR)


# ── config / camera helpers ──────────────────────────────────────────────────

def _camera_index() -> int:
    try:
        from core.config_loader import get_all_config
        return int(get_all_config().get("camera_index", 0) or 0)
    except Exception:
        return 0


def _open_camera():
    import platform
    try:
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
    except AttributeError:
        backend = 0
    cap = cv2.VideoCapture(_camera_index(), backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None
    for _ in range(6):  # warm-up frames
        cap.read()
    return cap


# ── scan-bar rendering ───────────────────────────────────────────────────────

def _draw_scan_bar(frame: np.ndarray, phase: float) -> np.ndarray:
    """Return a copy of the BGR frame with an animated scan bar sweeping
    bottom → top → bottom (triangle wave on `phase`)."""
    h, w = frame.shape[:2]
    pos = phase % 2.0
    pos = pos if pos <= 1.0 else 2.0 - pos
    y    = int((1.0 - pos) * (h - 1))
    band = max(6, h // 14)

    out = frame.copy()
    y0, y1 = max(0, y - band), min(h, y + band)
    if y1 > y0:
        region = out[y0:y1].astype(np.float32)
        falloff = 1.0 - (np.abs(np.arange(y0, y1) - y).astype(np.float32) / band)
        alpha = falloff[:, None, None] * 0.55
        glow = np.empty_like(region)
        glow[:] = _SCAN_COLOR
        out[y0:y1] = np.clip(region * (1 - alpha) + glow * alpha, 0, 255).astype(np.uint8)
    cv2.line(out, (0, y), (w, y), _SCAN_CORE, 2)
    return out


def _emit_frame(send_fn, frame: np.ndarray) -> None:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if ok and send_fn:
        send_fn(buf.tobytes())


# ── Gemini ───────────────────────────────────────────────────────────────────

def _analyze(photo: np.ndarray, query: str, api_key: str) -> dict:
    from google import genai
    from google.genai import types as gtypes

    # match screen_processor's upload size: max 1280 wide
    h, w = photo.shape[:2]
    if w > 1280:
        photo = cv2.resize(photo, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("could not encode photo")

    prompt = (
        "You are a nutrition analysis engine. Look at the food in this photo.\n"
        f'User\'s request (respond in the SAME language as this request): "{query}"\n'
        "Return ONLY minified JSON — no markdown fences, no extra text — with keys:\n"
        ' "food": short name of the dish/foods (null if NO food is visible),\n'
        ' "portion": estimated portion size as short text,\n'
        ' "calories_kcal": number (total estimate),\n'
        ' "carbs_g", "sugar_g", "fiber_g", "protein_g", "fat_g": numbers,\n'
        ' "panel_text": multi-line plain-text nutrition breakdown in the user\'s'
        " language — food name, portion, total calories, then one line per macro"
        " (carbs, sugar, fiber, protein, fat) with units; if several foods are"
        " visible add a short per-item calorie list; max 25 lines,\n"
        ' "spoken_summary": 1-2 conversational sentences in the user\'s language'
        " naming the food and total calories, mentioning it is an estimate."
        " If no food is visible, politely say so instead."
    )

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=_MODEL,
        contents=[
            gtypes.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"),
            prompt,
        ],
    )
    text = (resp.text or "").strip()

    # tolerate accidental fences / prose around the JSON
    if "{" in text and "}" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    return json.loads(text)


# ── entry point ──────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    query = (parameters.get("query") or "").strip() or "How many calories is this food?"

    from memory.config_manager import get_gemini_key
    api_key = get_gemini_key()
    if not api_key:
        return "I can't run the nutrition scan — no API key is configured."

    def _log(msg: str) -> None:
        if player:
            try:
                player.write_log(msg)
            except Exception:
                pass

    # Frontend camera stream via WsUI (graceful if unavailable)
    _send_frame = None
    if player and hasattr(player, "start_camera_stream"):
        _send_frame = player.start_camera_stream()
    view_open = _send_frame is not None

    cap = _open_camera()
    if cap is None:
        if view_open and hasattr(player, "stop_camera_stream"):
            player.stop_camera_stream()
        return ("I couldn't access the camera — it may be in use by another "
                "feature or application.")

    photo = None
    stop_anim = threading.Event()
    animator = None
    try:
        _log("Sirius: Nutrition scan started.")

        # Phase 1 — live preview with scan bar (user positions the food)
        t0 = time.time()
        last = None
        while time.time() - t0 < _LIVE_SCAN_SECONDS:
            ok, frm = cap.read()
            if ok and frm is not None:
                last = frm
                _emit_frame(_send_frame, _draw_scan_bar(frm, (time.time() - t0) * 1.2))
            time.sleep(1.0 / _FPS)
        ok, frm = cap.read()
        photo = frm if ok and frm is not None else last
    finally:
        try:
            cap.release()   # release BEFORE anything else — avoid device conflicts
        except Exception:
            pass

    if photo is None:
        if view_open and hasattr(player, "stop_camera_stream"):
            player.stop_camera_stream()
        return "I couldn't capture a picture of the food, sorry."

    # Phase 2 — freeze frame, keep the scan bar sweeping while Gemini analyzes
    if _send_frame:
        def _animate():
            a0 = time.time()
            while (not stop_anim.wait(1.0 / _FPS)
                   and time.time() - a0 < _ANIM_MAX_SECONDS):
                _emit_frame(_send_frame, _draw_scan_bar(photo, (time.time() - a0) * 1.2))
        animator = threading.Thread(target=_animate, daemon=True,
                                    name="calorie-scan-anim")
        animator.start()

    try:
        data = _analyze(photo, query, api_key)
    except Exception as e:
        return f"The nutrition analysis failed: {e}"
    finally:
        stop_anim.set()
        if animator:
            animator.join(timeout=1)
        if view_open and hasattr(player, "stop_camera_stream"):
            player.stop_camera_stream()   # back to the SIRIUS HUD

    spoken = (data.get("spoken_summary") or "").strip()

    if data.get("food"):
        panel = (data.get("panel_text") or "").strip()
        if player and panel:
            try:
                player.show_content("🍽 NUTRITION SCAN", panel)
            except Exception:
                pass
        _log(f"Sirius: Nutrition scan complete — {data.get('food')}"
             f" ≈ {data.get('calories_kcal')} kcal.")

    return spoken or "The scan finished, but I couldn't read the result."
