"""
TCP Companion Server — Receives notes and place visits from the Sirius Companion app.

Runs on port 8001 (one above the HTTP dashboard on 8000).
Protocol: JSON headers + binary attachments, per-item ACK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger("tcp_companion")

# Default vault path — user can override via config
_obsidian_vault_path: str | None = None
_notes_callback: Callable | None = None


def configure(vault_path: str | None = None, on_notes: Callable | None = None):
    global _obsidian_vault_path, _notes_callback
    if vault_path:
        _obsidian_vault_path = vault_path
    if on_notes:
        _notes_callback = on_notes


@dataclass
class TransferItem:
    uuid: str
    type: str  # "note" or "place_visit"
    category: str = ""
    title: str = ""
    content: str = ""
    ai_summary: str | None = None
    ai_tags: list[str] | None = None
    attachments: list[dict] = field(default_factory=list)
    content_length: int = 0
    raw_data: bytes = b""


async def _send_ack(writer: asyncio.StreamWriter, uuid: str, ok: bool, error: str | None = None,
                    result: dict | None = None):
    ack = json.dumps({"uuid": uuid, "ok": ok, "error": error, "result": result or {}}, ensure_ascii=False)
    writer.write(f"{ack}\n".encode())
    await writer.drain()


async def _read_json_line(reader: asyncio.StreamReader, timeout: float = 30) -> dict | None:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            return None
        return json.loads(line.decode().strip())
    except (asyncio.TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None


async def _handle_item(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, header: dict):
    """Process a single item (note or place_visit)."""
    uuid = header.get("uuid", "unknown")
    item_type = header.get("type", "")
    attachments_meta = header.get("attachments", [])
    content_length = header.get("content_length", 0)

    # Read attachment binary data if any.
    raw_data = b""
    remaining = sum(a.get("size", 0) for a in attachments_meta)
    while remaining > 0:
        chunk = await asyncio.wait_for(reader.read(min(remaining, 65536)), timeout=120)
        if not chunk:
            break
        raw_data += chunk
        remaining -= len(chunk)

    item = TransferItem(
        uuid=uuid,
        type=item_type,
        category=header.get("category", ""),
        title=header.get("title", ""),
        content=header.get("content", ""),
        ai_summary=header.get("ai_summary"),
        ai_tags=header.get("ai_tags"),
        attachments=attachments_meta,
        content_length=content_length,
        raw_data=raw_data,
    )

    ok = False
    error = None
    result = None
    try:
        if item_type == "note":
            result = await _process_note(item)
            ok = True
            _notify_sync("note", item.title or "Sem titulo")
        elif item_type == "place_visit":
            await _process_place_visit(item)
            ok = True
            _notify_sync("place_visit", item.title or item.category)
        else:
            error = f"Unknown item type: {item_type}"
    except Exception as e:
        error = str(e)
        logger.error(f"Failed to process item {uuid}: {e}")

    await _send_ack(writer, uuid, ok, error, result)


async def _process_note(item: TransferItem) -> dict:
    """Route a note into the Obsidian vault via the shared note organizer.

    The organizer picks the target file from the configured notes folder
    (obsidian_vault_path + obsidian_notes_subpath) and appends to it.
    """
    from actions.note_organizer import organize_note, save_images

    note_kwargs = dict(
        title=item.title,
        content=item.content,
        category=item.category,
        ai_summary=item.ai_summary,
        ai_tags=item.ai_tags,
        vault_path=_obsidian_vault_path,
        source_uuid=item.uuid,
    )
    organized = await organize_note(**note_kwargs) if item.content.strip() else None

    if item.content.strip() and organized is None:
        # No vault reachable — never drop a note: use the desktop fallback.
        fallback = Path.home() / "Desktop" / "sirius_notes"
        fallback.mkdir(parents=True, exist_ok=True)
        organized = await organize_note(**{**note_kwargs, "vault_path": str(fallback)})
    if item.content.strip() and organized is None:
        raise RuntimeError("Could not save note: no vault reachable")

    image_paths = []
    if item.attachments and len(item.raw_data) > 0 and not (organized and organized.duplicate):
        offset = 0
        attachments: list[tuple[str, bytes]] = []
        for att in item.attachments:
            name = att.get("name", "file")
            size = att.get("size", 0)
            chunk = item.raw_data[offset:offset + size]
            offset += size
            if len(chunk) != size:
                raise RuntimeError(f"Incomplete attachment: {name}")
            attachments.append((name, chunk))
        image_paths = await asyncio.to_thread(save_images, _obsidian_vault_path, attachments)

    target = organized.target if organized else (image_paths[0] if image_paths else None)
    logger.info("Note saved: %s", target)

    # Notify callback if registered.
    if _notes_callback:
        try:
            await _notes_callback(item)
        except Exception as e:
            logger.error(f"Notes callback failed: {e}")

    return {
        "target": str(target) if target else "",
        "summary": organized.summary if organized else None,
        "tags": organized.tags if organized else None,
        "duplicate": bool(organized and organized.duplicate),
        "images": [str(path) for path in image_paths],
    }


async def _process_place_visit(item: TransferItem):
    """Store a place visit record."""
    # For now, save as a JSON log. Future: integrate with analytics DB.
    log_dir = Path.home() / ".sirius" / "place_visits"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "visits.jsonl"

    record = {
        "uuid": item.uuid,
        "place_id": item.category,  # reuse category field for place_id
        "title": item.title,
        "content": item.content,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"Place visit recorded: {item.title}")


def _notify_sync(item_type: str, title: str) -> None:
    """Broadcast to React frontend and speak via TTS (fire-and-forget)."""
    def _worker():
        try:
            from ws_server import WsMessage, manager
            label = "anotação" if item_type == "note" else "visita"
            manager.broadcast_sync(WsMessage("sync_received", {
                "type": item_type,
                "title": title,
                "text": f"📱 {label} recebida: {title}",
            }))
        except Exception:
            pass
        try:
            from core.config_loader import get_all_config
            from core.tts import create_tts_player
            label = "anotação" if item_type == "note" else "visita registrada"
            tts = create_tts_player(get_all_config())
            tts.speak(f"{label} recebida: {title}")
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


async def start_tcp_server(host: str = "0.0.0.0", port: int = 8001):
    """Start the TCP companion server."""
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"Connection from {addr}")

        try:
            # Read session header.
            header = await _read_json_line(reader, timeout=10)
            if not header or header.get("version") != 1:
                logger.warning(f"Invalid header from {addr}")
                writer.close()
                return

            device_id = str(header.get("device_id", ""))
            session_key = str(header.get("session_key", ""))
            try:
                from core.config_loader import _read_json
                devices = _read_json("trusted_devices.json").get("devices", {})
                trusted = devices.get(device_id, {})
            except Exception:
                trusted = {}
            if not device_id or not session_key or session_key != trusted.get("session_key"):
                logger.warning("Rejected unauthenticated TCP companion connection from %s", addr)
                writer.close()
                return
            total_items = header.get("total_items", 0)
            logger.info(f"Session: {total_items} items from device {header.get('device_id', '?')}")

            # Process items sequentially.
            for i in range(total_items):
                item_header = await _read_json_line(reader, timeout=30)
                if not item_header:
                    logger.warning(f"Expected item header {i+1}/{total_items} but got none")
                    break
                await _handle_item(reader, writer, item_header)

        except Exception as e:
            logger.error(f"Handler error from {addr}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, host, port)
    logger.info(f"TCP Companion Server listening on {host}:{port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    asyncio.run(start_tcp_server())
