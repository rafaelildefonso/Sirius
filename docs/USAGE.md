# Guia de Uso — SIRIUS + Companion App

## Índice

1. [Rodar o SIRIUS no PC](#1-rodar-o-sirius-no-pc)
2. [Instalar o Companion no Celular](#2-instalar-o-companion-no-celular)
3. [Configurar o IP](#3-configurar-o-ip)
4. [Parear Celular com PC](#4-parear-celular-com-pc)
5. [Funcionalidades do App](#5-funcionalidades-do-app)
6. [IA Local (Gemma)](#6-ia-local-gemma)
7. [Solução de Problemas](#7-solução-de-problemas)

---

## 1. Rodar o SIRIUS no PC

Abra um terminal na pasta do Sirius:

```powershell
cd sirius-ui
npx tauri dev
```

> Para **build de produção**, execute `npx tauri build` dentro de `sirius-ui/`.
> O backend usa cache incremental; para forçar uma recompilação, execute
> `python build_backend.py --force` antes do build.

O servidor do dashboard será iniciado na porta **8000**. Deixe os terminais abertos.

> **Firewall:** Se o celular não conectar, libere a porta 8000 no firewall do Windows.

---

## 2. Instalar o Companion no Celular

### Pré-requisitos

- Android 8.0+ (API 26)
- Celular conectado ao mesmo Wi-Fi que o PC
- USB debugging ativado (para instalar via ADB)
- Flutter SDK 3.11+ instalado no PC

### Gerar o APK

```bash
.\build_companion.ps1 -Mode debug
```

### Instalar

```bash
# Opção 1 — ADB (celular conectado via USB)
flutter install

# Opção 2 — Manual
# Copie sirius_companion/build/app/outputs/flutter-apk/app-debug.apk para o celular
# Abra o arquivo no celular e instale
```

> **Ativar USB Debugging:** Ajustes → Sobre o telefone → Toque 7x em "Número da build" → Volte → Sistema → Opções do desenvolvedor → Ative "Depuração USB".

---

## 3. Configurar o IP

Descubra o IP do PC:

```powershell
# Windows
ipconfig
```

Anote o IPv4 (ex: `192.168.1.100`).

Edite `sirius_companion/lib/core/config/constants.dart`:

```dart
static const String defaultBaseUrl = 'http://192.168.1.100:8000';
```

Substitua pelo IP do seu PC e rebuild o APK.

---

## 4. Parear Celular com PC

1. Abra o **SIRIUS Companion** no celular
2. Toque em **Configurações** (engrenagem no canto superior direito)
3. Selecione **Parear com PC**
4. Escolha um método:
   - **QR Code** — Aponte para o QR code no painel do PC (`http://PC_IP:8000`)
   - **Chave Manual** — Digite a chave de 6 caracteres exibida no painel
5. Confirme o pareamento no PC quando solicitado

Após pareado, o app sincroniza automaticamente a cada 15 minutos.

---

## 5. Funcionalidades do App

### Tela Inicial

| Item | Descrição |
|------|-----------|
| Status da conexão | Conectado/Desconectado do PC |
| Última sincronização | Timestamp da última sync |
| Comandos pendentes | Quantidade aguardando envio |
| Meus Lugares | Locais monitorados por geofence |

### Comandos

- Toque no campo de texto na tela inicial
- Digite o comando (ex: "lembrar de comprar pão")
- O app tenta processar localmente com Gemma
- Se falhar, enfileira para o PC processar na próxima sincronização

### Geofencing (Lugares)

1. Toque em **Meus Lugares**
2. Toque em **+** para adicionar um local
3. Escolha no mapa ou digite coordenadas
4. Defina nome e raio
5. Ao entrar/sair do local, uma notificação aparece:
   - **Confirmar** → registra a visita
   - **Ignorar** → descarta

### Sincronização

- Automática: a cada 15 min (WorkManager, mesmo com app fechado)
- Manual: puxe para atualizar na tela inicial
- Backoff exponencial em falha: 30s → 2min → 10min → 1h
- Dados persistem no SQLite local até confirmação do servidor

---

## 6. IA Local (Gemma)

O app pode processar comandos localmente usando o modelo **Gemma 2B int4** (~1.5 GB).

### Requisitos

- Android com **Vulkan** (Adreno 6xx+, Mali G7x+)
- **3 GB+** de RAM livre
- **2 GB** de espaço interno

### Ativar

1. Vá em **Configurações → IA Local (Gemma)**
2. Toque em **Baixar / Inicializar**
3. O app verifica o hardware automaticamente
4. Se compatível, faz o download do modelo (pode levar alguns minutos)
5. Após baixado, comandos são processados localmente

### Fallback

Se o hardware não for compatível ou o processamento falhar, o comando é enviado como `gemma_fallback` para o PC processar. O fallback é **automático e transparente**.

### Gerenciar

- **Descarregar**: Libera a RAM do modelo (no mesmo menu)
- **Status**: Disponível / Incompatível / Baixando / Pronto / Erro

---

## 7. Solução de Problemas

| Problema | Causa | Solução |
|----------|-------|---------|
| "Servidor não encontrado" | IP errado ou firewall | Verifique IP com `ipconfig`, libere porta 8000 |
| Pareamento falha | Redes diferentes | PC e celular no mesmo Wi-Fi |
| Gemma "Hardware incompatível" | Sem Vulkan ou RAM insuficiente | Fallback automático, sem ação necessária |
| Download do Gemma trava | Rede lenta ou pouco espaço | Libere 2 GB, reinicie o download |
| Sincronização não roda | Economia de bateria | Desative economia de bateria para o SIRIUS Companion |
| APK grande (~30 MB) | Normal (Gemma + MediaPipe) | Apenas debug contém símbolos extras |
| "flutter: app not installed" | Versão anterior conflitando | Desinstale o app antigo antes |

---

## Links Úteis

- [Repositório SIRIUS](https://github.com/rafaelildefonso/sirius)
- [Documentação Flutter](https://docs.flutter.dev)
- [Gemma 2B - Google](https://ai.google.dev/gemma)
