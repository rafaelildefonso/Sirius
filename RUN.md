# 🚀 Como Rodar o OpenJarvis

Guia rápido para iniciar o projeto (backend + frontend).

---

## 📋 Pré-requisitos

| Ferramenta | Como verificar |
|------------|----------------|
| **Python 3.10+** | `python --version` |
| **uv** | `uv --version` |
| **Node.js 20+** | `node --version` |
| **npm** | `npm --version` |

> Se falta alguma ferramenta, veja a seção **Instalação de Pré-requisitos** abaixo.

---

## 🎯 Modo Rápido (Recomendado)

### Terminal 1 - Backend (API Server)
```powershell
uv run jarvis serve
```

O servidor inicia em: `http://localhost:8000`

### Terminal 2 - Frontend (Interface Web)
```powershell
cd frontend
npm install   # só na primeira vez
npm run dev
```

O frontend inicia em: `http://localhost:5173`

### Acesse no navegador:
👉 **http://localhost:5173**

---

## 🔧 Instalação de Pré-requisitos

### 1. uv (Python Package Manager)
**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Node.js
Baixe em: https://nodejs.org/ (versão LTS recomendada)

Ou via winget no Windows:
```powershell
winget install OpenJS.NodeJS
```

---

## 🧠 Configurando a Inteligência (LLM)

O Jarvis precisa de um backend de IA. Escolha uma opção:

### Opção A: Ollama (Local - Gratuito)

1. **Instale o Ollama:**
   - Windows: `winget install Ollama.Ollama`
   - Ou baixe em: https://ollama.com

2. **Inicie o servidor Ollama:**
   ```powershell
   ollama serve
   ```

3. **Baixe um modelo:**
   ```powershell
   ollama pull gemma3:1b
   ```

4. **Inicie o Jarvis com Ollama:**
   ```powershell
   uv run jarvis serve --engine ollama
   ```

### Opção B: API na Nuvem (OpenAI, Anthropic, etc.)

1. **Configure sua chave de API:**
   ```powershell
   $env:OPENAI_API_KEY = "sk-..."
   # ou
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   ```

2. **Inicie o Jarvis:**
   ```powershell
   uv run jarvis serve --engine cloud
   ```

---

## 🎨 Comandos Úteis

### Verificar diagnóstico
```powershell
uv run jarvis doctor
```

### Testar sem frontend
```powershell
uv run jarvis ask "Qual a capital da França?"
```

### Chat interativo no terminal
```powershell
uv run jarvis chat
```

### Ver modelos disponíveis
```powershell
uv run jarvis model list
```

### Ver status do servidor
```powershell
uv run jarvis status
```

---

## 🐛 Problemas Comuns

### "Server dependencies not installed"
```powershell
uv sync --extra server
```

### "No inference engine available"
- Verifique se o Ollama está rodando: `ollama serve`
- Ou configure uma chave de API de nuvem

### Porta 8000 ou 5173 em uso
```powershell
# Backend em porta diferente
uv run jarvis serve --port 8080

# Frontend em porta diferente
# Edite vite.config.ts ou use:
npm run dev -- --port 3000
```

---

## 🎙️ Assistente de Voz (Novo!)

Converse com a IA usando apenas a voz - modo "Push-to-Talk".

### Como usar:

1. **Certifique-se que o Ollama está rodando:**
   ```powershell
   ollama serve
   ```

2. **Inicie o assistente de voz:**
   ```powershell
   uv run python voice-assistant.py
   ```

3. **Controles:**
   - Segure **Ctrl+Space** → fale → solte
   - A IA ouve, processa e responde por voz
   - Pressione **Escape** para fechar

### Tecnologias usadas:
| Componente | Tecnologia | Tipo |
|------------|-----------|------|
| **STT** | speech_recognition + Google API | ⚠️ Requer internet (gratuito) |
| **LLM** | Ollama + gemma3 (local) | ✅ 100% local |
| **TTS** | pyttsx3 (Windows SAPI) | ✅ 100% local |

> **Nota:** STT usa Google Speech API (gratuito mas requer internet). Para STT 100% local, instale o modelo whisper: `ollama pull qwen3.5:2b` e aguarde download do modelo de voz (~800MB).

### Testar antes de usar:
```powershell
uv run python voice_assistant/test_setup.py
```

---

## 📁 Estrutura do Projeto

```
jarvis/
├── src/                  # Backend Python
├── frontend/             # Frontend React + Vite
├── voice_assistant/      # Assistente de voz desktop
│   ├── main.py          # Orquestrador principal
│   ├── audio.py         # Gravação/reprodução
│   ├── stt.py           # Speech-to-Text
│   ├── tts.py           # Text-to-Speech
│   ├── llm.py           # Comunicação Ollama
│   ├── hotkey.py        # Atalhos de teclado
│   └── ui.py            # Interface Tkinter
├── voice-assistant.py   # Launcher standalone voz
├── run-integrated.py    # Launcher integrado (Web + Voz)
├── configs/             # Configurações de exemplo
└── RUN.md              # Este arquivo
```

---

## 🖥️ Modo Desktop Tauri (App Windows Nativo)

Execute o frontend como um aplicativo Windows nativo (sem navegador):

```powershell
# Instalar dependências do Tauri (primeira vez)
cd frontend
npm install

# Voltar na raiz e executar
uv run python run-tauri.py
```

Isso abre:
- **🖥️ App Desktop** - Interface nativa em janela própria
- **�️ Voice Mode** - Clique em "Voice Call" no sidebar para abrir janela de voz
- **🔧 Backend** - API rodando em background

### ✨ Recursos do App Desktop:
- Interface nativa (WebView2) - não precisa de navegador
- Janela de voz flutuante e sempre no topo
- Integração com atalhos de teclado do sistema
- Ícone na bandeja do Windows

---

## 🎯 Modo Integrado (Web)

Execute Web e Voz juntos com interface de seleção:

```powershell
uv run python run-integrated.py
```

Isso abre uma janela para escolher:
- **🌐 Modo Web** - Interface web completa no navegador
- **🎙️ Modo Voz** - Assistente de voz em tela cheia
- **⚡ Ambos** - Web no navegador + Voz em janela separada

### 🔄 Acesso pelo Frontend

Na interface web, clique em **"Voice Call"** no sidebar para alternar para o modo voz.

Ou acesse diretamente: `http://localhost:5173/voice`

### Para compilar pra distribuição (.exe):

```powershell
cd frontend
npm run tauri build
```

---

## 💡 Dicas

- **Primeira vez?** Use `uv run jarvis init` para configuração interativa
- **Ambiente de desenvolvimento:** O frontend recarrega automaticamente ao salvar arquivos
- **Hot reload:** Ambos (backend e frontend) suportam recarga automática

---

## 📚 Documentação Oficial

- **Docs:** https://open-jarvis.github.io/OpenJarvis/
- **GitHub:** https://github.com/open-jarvis/OpenJarvis

---

*Última atualização: Maio 2026*
