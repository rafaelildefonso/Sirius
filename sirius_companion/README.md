# SIRIUS Companion

Aplicativo Android companion para o [SIRIUS](https://github.com/rafaelildfonso/sirius) - Assistente pessoal com IA.

Funciona como extensão do seu PC: coleta contexto (localização), permite envio de comandos offline/online, e processa comandos localmente com IA on-device (Gemma 2B).

## Requisitos

| Item | Mínimo | Recomendado |
|------|--------|-------------|
| Android | 8.0 (API 26) | 12+ (API 31+) |
| RAM | 3 GB | 6 GB+ |
| GPU | Vulkan (para Gemma local) | Adreno 6xx+ / Mali G7x+ |
| PC | SIRIUS rodando com `SIRIUS_WS_UI=1` | Porta 8000 acessível |

## Build e Instalação

### 1. Gerar o APK

```bash
# Navegue até a pasta do app
cd sirius_companion

# Gerar APK de debug
flutter build apk --debug

# Ou APK de release (precisa de keystore configurado)
flutter build apk --release
```

O APK estará em `build/app/outputs/flutter-apk/app-debug.apk` (ou `app-release.apk`).

### 2. Instalar no celular

```bash
# Com o celular conectado via USB (adb)
flutter install

# Ou copie o APK para o celular e instale manualmente
```

### 3. Ativar modo desenvolvedor no celular

1. Ajustes → Sobre o telefone → Toque 7x em "Número da build"
2. Volte → Sistema → Opções do desenvolvedor
3. Ative "Depuração USB"
4. Ative "Instalar via USB"

## Configuração Inicial

### 1. Descobrir o IP do PC

No PC, abra o terminal e execute:

```bash
# Windows
ipconfig
# Linux/macOS
ifconfig
```

Anote o endereço IPv4 (ex: `192.168.1.100`).

### 2. Iniciar o SIRIUS no PC

```powershell
$env:SIRIUS_WS_UI='1'
python main.py
```

O servidor HTTP do dashboard será iniciado na porta **8000**.

### 3. Configurar o IP no app

Edite o arquivo `lib/core/config/constants.dart` e altere o IP:

```dart
static const String defaultBaseUrl = 'http://192.168.1.100:8000';
```

Substitua `192.168.1.100` pelo IP do seu PC.

> Para evitar ter que rebuildar toda vez que o IP mudar, futuramente o app terá configuração dinâmica.

### 4. (Opcional) Build com IP dinâmico

Se quiser testar sem recompilar, use o **QR Code** na tela de pareamento - o app detecta automaticamente o IP do servidor.

## Pareamento (Phone → PC)

1. Abra o **SIRIUS Companion** no celular
2. Na tela inicial, toque em **"Configurações"** (ícone de engrenagem)
3. Vá em **"Parear com PC"**
4. Escolha um método:
   - **QR Code**: Aponte para o QR Code exibido no painel do Sirius (dashboard em `http://PC_IP:8000`)
   - **Chave Manual**: Digite a chave de 6 caracteres exibida no dashboard
5. Confirme o pareamento no PC quando solicitado
6. Pronto! O app está conectado.

## Funcionalidades

### Tela Inicial

- **Status da Conexão**: Mostra se está conectado ao PC
- **Última Sincronização**: Quando foi a última vez que os dados foram enviados
- **Comandos Pendentes**: Quantos comandos aguardam sincronização
- **Meus Lugares**: Acesso rápido à tela de locais monitorados

### Comandos Offline

- Na tela inicial, toque no microfone ou campo de texto
- Digite ou fale o comando
- O app tenta processar localmente com **Gemma**
- Se o processamento local falhar, o comando é enfileirado como `gemma_fallback` e enviado ao PC na próxima sincronização
- Os comandos são sincronizados automaticamente a cada 15 minutos (WorkManager)

### Geofencing (Lugares)

1. Na tela inicial, toque em **"Meus Lugares"**
2. Toque em **"+"** para adicionar um novo local
3. Escolha no mapa ou digite coordenadas
4. Defina um nome e raio de detecção
5. Ao entrar/sair do local, você recebe uma notificação:
   - **"Confirmar"** → registra a visita
   - **"Ignorar"** → descarta

### IA Local (Gemma 2B)

1. Vá em **Configurações → IA Local (Gemma)**
2. Toque em **"Baixar / Inicializar"**
3. O app verifica se o hardware é compatível (RAM ≥ 3GB + Vulkan)
4. Se compatível, faz o download do modelo (~1.5 GB)
5. Após baixado, o modelo fica ativo e processa comandos localmente
6. Para descarregar, toque em **"Descarregar"**

> Se o hardware não for compatível, o app envia os comandos brutos para o PC processar (fallback automático).

### Sincronização

- Automática: a cada 15 minutos via WorkManager (mesmo com app fechado)
- Manual: puxe para atualizar na tela inicial
- Backoff exponencial em caso de falha (30s → 2min → 10min → 1h)
- Dados são mantidos no banco local até confirmação do servidor

## Estrutura do App

```
sirius_companion/
├── lib/
│   ├── main.dart                    # Entry point
│   ├── core/
│   │   ├── ai/                      # GemmaEngine + AiService
│   │   ├── config/                  # Constantes, enums
│   │   ├── network/                 # API Client (Dio)
│   │   ├── storage/                 # Drift DB, repos, models
│   │   ├── sync/                    # SyncWorker (WorkManager)
│   │   └── device_identity.dart     # UUID + Keystore
│   └── features/
│       ├── home/                    # Tela inicial + Settings
│       ├── locations/               # Geofencing + Places
│       └── pairing/                 # QR Code + pareamento
└── android/
    └── app/src/main/kotlin/.../
        └── GemmaModule.kt           # Bridge Kotlin → MediaPipe
```

## Resolução de Problemas

| Problema | Causa | Solução |
|----------|-------|---------|
| "Servidor não encontrado" | IP errado ou firewall | Verifique IP, desative firewall na porta 8000 |
| "Falha no pareamento" | App e PC em redes diferentes | Ambos devem estar na mesma rede Wi-Fi |
| Gemma "Hardware incompatível" | Celular sem Vulkan ou RAM insuficiente | Use fallback (automático) |
| Gemma trava no download | Rede lenta ou espaço insuficiente | Libere ~2 GB, tente novamente |
| Sincronização não funciona | WorkManager pode estar suspenso | Desative economia de bateria para o app |
| APK muito grande | Gemma + MediaPipe ~20 MB extras | É normal, esperado |

## Desenvolvimento

Para contribuir com o desenvolvimento:

```bash
# Instalar dependências
cd sirius_companion
flutter pub get

# Gerar código (drift, json, freezed)
dart run build_runner build --delete-conflicting-outputs

# Verificar análise estática
flutter analyze

# Testes
flutter test
```

### Requisitos de Build

- Flutter SDK 3.11+ (canal stable)
- Android Studio ou linha de comando
- Kotlin 1.9+
- Gradle 8.x
