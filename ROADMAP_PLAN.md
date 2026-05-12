# 🚀 Sirius Project Roadmap

Este documento descreve o plano de desenvolvimento do Sirius para se tornar um assistente pessoal completo, multiplataforma e integrado ao workflow do usuário.

## ✅ Concluído (Fase 1: Fundação)

- [x] Transcrição local (Whisper) e síntese de voz (EdgeTTS).
- [x] Suporte a LLM Local (Ollama) e Cloud (Groq/Gemini).
- [x] Interface UI com legendas e status.
- [x] Ferramentas básicas: Busca Web e YouTube.
- [x] **Persistência de Memória:** Sirius agora lembra nomes e preferências do usuário.
- [x] **Controle de PC Básico:** Digitação, teclas e abertura de apps.

## 🚧 Em Progresso (Fase 2: Controle e Estabilidade - foco 100% PC)

- [x] **Controle de PC Avançado (base já funcional):**
  - [x] Módulo de Workspaces (abrir vários apps/sites de uma vez).
  - [x] Manipulação de janelas e processos.
  - [x] Acesso a arquivos locais.
- [ ] **Mensagens com confirmação:** envio agora exige prévia e `confirmed=yes`.
- [ ] **Hardening de tools sensíveis:** camada central de confirmação para ações críticas (digitação, atalhos, fechamento de janela, envio de mensagens, ações perigosas do sistema).
- [ ] **API backend sem placeholders críticos:** rotas de skills e optimize com execução real.

## 📅 Planejado (Fase 3: Produtividade e Organização)

- [ ] **Módulo de Secretário:**
  - [x] Integração com Calendário (Google/Outlook) já existe no core.
  - [x] Gerenciamento de Tarefas e Lembretes (lembretes OK).
  - [x] Workspaces: comando para abrir conjunto de apps/sites para tarefa específica.
- [x] **Visão Computacional:**
  - [x] "O que você está vendo?": Tirar screenshot e analisar com modelo Vision.

## 📱 Futuro (Fase 4: Multiplataforma e Ecossistema - após estabilizar PC)

- [ ] **Versão Mobile:** App para Android/iOS.
- [ ] **Sincronia PC-Mobile:**
  - [ ] "Pegue esse arquivo do PC e mande pro meu celular".
  - [ ] Notificações compartilhadas.
- [ ] **Agentes Autônomos:** Executar tarefas longas em background e avisar quando terminar.

---

## 💡 Ideias Adicionais

- **Modo Gamer:** Reduzir prioridade de CPU do Sirius durante jogos e permitir controle de música/discord por voz sem sair do jogo.
- [~] **Integração Home Assistant:** Controlar luzes e dispositivos inteligentes da casa.
- **Clonagem de Voz:** Permitir que o usuário use uma voz personalizada.
