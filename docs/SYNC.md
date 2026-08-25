# SYNC.md — Sincronização Celular ↔ PC

Como e quando os dados do celular chegam ao PC no SIRIUS. Cobre o dashboard web
(navegador do celular) e o app companion Flutter (`sirius_companion/`).

---

## 1. Visão geral

Existem **dois canais distintos**, ambos terminando no `dashboard/server.py`
(HTTP puro na porta 8000, rede local):

```
NAVEGADOR DO CELULAR (app.html servido pelo PC)     APP FLUTTER (sirius_companion)
  tempo real: comandos + microfone via WebSocket      HTTP em lote (store-and-forward)
  |                                                   |
  | GET /auto-login?key=XXX  (QR, uma vez)            | POST /api/device/pair {pair_key}
  |   -> token de sessão                              |   <-> device_token + session_key
  | WS /ws?token=           (persistente)             |
  |   <- {"type":"command", "enc"|"text"}             | WorkManager: a cada 15 min
  | POST /api/command                                 | Foreground : a cada 45 s
  | POST /api/wake                                    | Eventos    : criar/concluir/sonecar task
  | POST /api/upload                                  | Manual     : botão de sync
  | WS /ws/phone-audio?token=                         |
  |   <- PCM16 mono 16 kHz (~64 ms/frame)             | GET /api/device/ping
  |                                                   | POST /api/sync/batch {items[]}
  v                                                   | GET  /api/device/sync/pull
dashboard/server.py :8000                             v
  |
  |-- _command_queue -----> main.py::_process_dashboard_commands --> sessão Gemini Live
  |-- _phone_audio_queue -> main.py::_relay_phone_audio -----------> entrada realtime Gemini
  |-- tasks ---------------> SQLite (persistence.Repository) ------> scheduler do PC
  '-- _pending_phone_commands --> puxados pelo app no próximo sync (push PC→celular)
```

## 2. Pareamento (fluxo seguro)

A one-time key tem 6 caracteres (sem O/I/L/0/1), expira em 10 min e é de uso
único (`DashboardServer.new_key()`).

### Via QR code (caminho principal)

1. Usuário clica em "Controle Remoto" no PC → `remote_key` com QR contendo
   `http://IP:8000/auto-login?key=XXXXXX`.
2. App escaneia: extrai origem do PC **e** a key
   (`pairing_controller.dart::processQrCode`).
3. App chama `POST /api/device/pair` com `{device_id, device_name, ..., pair_key}`.
4. Servidor valida a key contra as keys pendentes:
   - **válida** → consome a key, aprova o device e responde
     `{ok, paired: true, device_token, session_key}`
     (a própria key vira a session_key, mesmo padrão do navegador);
   - **inválida/expirada** → `401 {"error": "Invalid or expired pairing code"}`.
5. App guarda `device_token` + `session_key` em `FlutterSecureStorage`.

### Sem key (pareamento manual)

1. App chama `POST /api/device/pair` sem `pair_key`.
2. Servidor coloca o device em `_pending_pair` e responde
   `409 {pending_approval: true, nonce}` + broadcast `pair_request`.
3. O popup **PairRequestDialog** aparece no sirius-ui (via ponte
   `_on_pair_request` → `ws_server.notify_pair_request` → mensagem WS
   `pair_request`). Aprovar/Rejeitar envia `{type: "pair_approve"}`.
4. Enquanto aguarda, o app faz polling em
   `GET /api/device/pair/status?device_id=..&nonce=..` (3 s). O `nonce`
   devolvido no passo 2 prova que quem pergunta é o próprio solicitante —
   sem ele, ninguém pode colher o token alheio conhecendo só o device_id.
5. Ao aprovar: device vai para `trusted_devices.json` (criptografado) com
   `session_key` nova; o app recebe `device_token` + `session_key` no poll.

> Dispositivos já pareados que chamarem `/api/device/pair` de novo recebem um
> token novo imediatamente (re-pareamento transparente).

## 3. Criptografia do sync (AES-256-CBC)

Mesmo esquema do dashboard web (`server.py::_derive_key`):

- **Chave AES** = `SHA-256(session_key || "SIRIUS-DASHBOARD-v1")` — 256 bits.
- **Formato** = `base64(IV[16] || ciphertext)`, CBC + PKCS7, IV aleatório por
  mensagem.
- **Push** (`POST /api/sync/batch`): cada item cifrado individualmente —
  `{client_id, type, payload: "<b64>", enc: true}`.
- **Pull** (`GET /api/device/sync/pull`): com session_key, todo item sai como
  `{"enc": true, "payload": "<b64>"}` e a resposta marca `"enc": true`.
- Compatibilidade: payload em texto plano ainda é aceito (devices legados), mas
  devices pareados após esta versão sempre cifram.
- Implementação Dart: `core/crypto/aes_cipher.dart` (pacotes `crypto` +
  `encrypt`). Python: helpers `_encrypt_cbc`/`_decrypt_cbc` (pacote
  `cryptography`, já usado pelo projeto).

**Limitação conhecida:** a session_key viaja uma única vez em texto plano na
resposta do pair (HTTP na LAN). TLS mútuo seria a solução completa; fora do
escopo atual. Risco restrito à rede local.

## 4. Endpoints do companion app

Todos exigem headers `Authorization: Bearer <device_token>` +
`X-Device-ID` (`_validate_device_token`).

| Endpoint | Método | Quando é chamado | Payload / resposta |
|---|---|---|---|
| `/api/device/pair` | POST | escaneou QR / pareamento manual | `{..., pair_key?, nonce?}` → token + session_key ou 409 pending |
| `/api/device/pair/status` | GET | polling durante aprovação (3 s) | query `device_id`+`nonce` → status/token |
| `/api/device/ping` | GET | antes de todo ciclo de sync | headers only → `{ok, status, server_time}` |
| `/api/sync/batch` | POST | cada ciclo de sync (push) | `{items:[{client_id,type,payload,enc}]}` ≤100 itens |
| `/api/device/sync/pull` | GET | cada ciclo de sync (pull) | → `{commands[], places[], tasks[]}` |

## 5. Tipos de item sincronizados (celular → PC)

| type | Gatilho no celular | Destino no PC |
|---|---|---|
| `command` | reservado | fila `_command_queue` → Gemini |
| `gemma_fallback` | Gemma local falhou/vazio → escala pro PC | fila `_command_queue` → Gemini |
| `place_confirmation` | geofence ENTER/EXIT/DWELL confirmado | ack (processado) |
| `quick_task` | usuário cria lembrete no app | SQLite `add_scheduled_task` |
| `task_done` / `task_snooze` | alarme dispensado/adiado | SQLite `complete/snooze_scheduled_task` |

Retry: itens que falham voltam à fila com backoff exponencial
(30 s → 2 min → 10 min → 1 h); após 10 tentativas viram dead-letter
(`constants.dart`).

## 6. Push PC → celular

- `DashboardServer.queue_phone_command(payload, device_id=None)` enfileira a
  mensagem para o device específico ou para todos.
- A tool **`send_to_phone`** ("SIRIUS, envie X pro meu celular") usa esse método;
  o app recebe no próximo pull e mostra notificação local
  (`sync_worker.dart::_processIncomingCommand`) — sem re-enfileirar (o que
  causaria loop de sync).
- Tasks criadas por voz no PC também chegam ao celular: o pull retorna sempre
  as tasks ativas do SQLite (`get_active_scheduled_tasks`) e o
  `TaskAlarmService.syncFromServer` arma os alarmes locais.

## 7. Timings do app Flutter

| Mecanismo | Frequência | Código |
|---|---|---|
| WorkManager periódico | 15 min (+ tarefa única 10 s após registro) | `sync_worker.dart::initWorkManager` |
| Sync em foreground | 45 s com app aberto; catch-up ao abrir/regain de rede | `foreground_sync.dart` |
| Event-driven | criar/concluir/sonecar dispara sync ~1 s depois | `TaskAlarmService` → `SyncWorker.triggerSync` |
| Manual | botão na home | `home_controller.dart` |

Cada ciclo `performSync()`: restaurar URL salva → ping → push pendentes →
pull → limpar sincronizados → salvar timestamp. Não há heartbeat/socket
persistente do app; presença é inferida por `last_seen` (ping/sync).

## 8. Fluxo interno no PC (até o Gemini)

- **Comandos** (web/app): `_command_queue` →
  `main.py::_process_dashboard_commands` espera até 8 s por sessão ativa e
  injeta via `session.send_client_content(...)`.
- **Microfone do celular**: `/ws/phone-audio` → `_phone_audio_queue` (máx 200
  frames ≈ 12,8 s; frames descartados se cheio) →
  `main.py::_relay_phone_audio`: silencia o mic do PC enquanto o celular
  transmite, devolve o mic após 1 s de silêncio.
- **Tasks**: escritas direto no SQLite; o `core/task_alarm.start_scheduler`
  dispara toasts no PC e o pull espelha para o celular.

## 9. Segurança — modelo de ameaças e limites

| Camada | Proteção |
|---|---|
| Pareamento | one-time key consumível OU aprovação manual no PC; nonce protege o polling de status |
| Tokens | bearer aleatório de 32 bytes; devices salvos em config criptografada |
| Sync | payloads AES-256-CBC com chave derivada da session_key |
| Áudio/comandos do navegador | AES opcional por sessão (CryptoJS no app.html) |
| Transporte | HTTP plano na LAN (limitação conhecida; ver §3) |

## 10. Troubleshooting

- **Pareamento não completa**: confira o log `[Dashboard] Pairing request
  pending approval` e se o sirius-ui está conectado (o prompt só aparece com UI
  aberta); para QR, verifique expiração da key (10 min).
- **Sync não acontece**: app precisa estar pareado e o servidor alcançável
  (`/api/device/ping`). Logs: `[SyncWorker]`.
- **Falha de descriptografia** (`Decryption failed` no batch): session_key
  divergente entre app e PC → re-parear regenera ambas.
- **Porta 8000 bloqueada**: firewall é aberto automaticamente na primeira vez
  (`_ensure_network_access`).
