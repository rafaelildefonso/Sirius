# 🚀 Sirius Project Roadmap

Este documento descreve o plano de desenvolvimento do Sirius para se tornar um assistente pessoal completo, multiplataforma e integrado ao workflow do usuário.

## ✅ Concluído (Fase 1: Fundação)

- [x] Interface de voz com Push-to-Talk (Ctrl+Space).
- [x] Transcrição local (Whisper) e síntese de voz (EdgeTTS).
- [x] Suporte a LLM Local (Ollama) e Cloud (Groq).
- [x] Interface UI com legendas e status.
- [x] Ferramentas básicas: Busca Web e YouTube.
- [x] **Persistência de Memória:** Sirius agora lembra nomes e preferências do usuário.
- [x] **Controle de PC Básico:** Digitação, teclas e abertura de apps.

## 🚧 Em Progresso (Fase 2: Controle e Estabilidade - foco 100% PC)

- [x] **Controle de PC Avançado (base já funcional):**
  - [x] Módulo de Workspaces (abrir vários apps/sites de uma vez).
  - [x] Manipulação de janelas e processos.
  - [~] Acesso a arquivos locais (parcial; precisa padronizar permissões e escopo).
- [x] **Mensagens com confirmação:** envio agora exige prévia e `confirmed=yes`.
- [x] **Hardening de tools sensíveis:** camada central de confirmação para ações críticas (digitação, atalhos, fechamento de janela, envio de mensagens, ações perigosas do sistema).
- [x] **API backend sem placeholders críticos:** rotas de skills e optimize com execução real.

## 📅 Planejado (Fase 3: Produtividade e Organização)

- [ ] **Módulo de Secretário:**
  - [~] Integração com Calendário (Google/Outlook) já existe no core, falta UX integrada no Sirius.
  - [~] Gerenciamento de Tarefas e Lembretes (lembretes OK, falta fluxo completo de tarefas).
  - [x] Workspaces: comando para abrir conjunto de apps/sites para tarefa específica.
- [ ] **Visão Computacional:**
  - [ ] "O que você está vendo?": Tirar screenshot e analisar com modelo Vision.

## 📱 Futuro (Fase 4: Multiplataforma e Ecossistema - após estabilizar PC)

- [ ] **Versão Mobile:** App para Android/iOS.
- [ ] **Sincronia PC-Mobile:**
  - [ ] "Pegue esse arquivo do PC e mande pro meu celular".
  - [ ] Notificações compartilhadas.
- [ ] **Agentes Autônomos:** Executar tarefas longas em background e avisar quando terminar.

---

## Estado Atual (Before/After desta execução)

### Before
- Shell tool com inconsistência de status em saídas do backend Rust.
- Envio de mensagens sem confirmação obrigatória.
- Endpoints de skills/optimize com placeholders.
- Roadmap desatualizado em relação ao que já existia no código.

### After
- `shell_exec` retorna sucesso/erro de acordo com `Exit code` real.
- `send_message` faz prévia e só envia com `confirmed=yes`.
- `ToolExecutor` aplica confirmação central para tools sensíveis no desktop.
- API de skills instala/remove de fato; optimize cria run real e persiste.
- Roadmap atualizado para trilha de entrega PC-first.

## 💡 Ideias Adicionais

- **Modo Gamer:** Reduzir prioridade de CPU do Sirius durante jogos e permitir controle de música/discord por voz sem sair do jogo.
- **Integração Home Assistant:** Controlar luzes e dispositivos inteligentes da casa.
- **Clonagem de Voz:** Permitir que o usuário use uma voz personalizada.
