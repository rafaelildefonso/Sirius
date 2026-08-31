# Browser Control — Guia Completo

## Visão Geral

`actions/browser_control.py` é o módulo principal de automação web via **Playwright**. A IA usa a ferramenta `browser_control` para todas as interações com navegadores.

---

## Ações Disponíveis

### Navegação Básica

| Ação | Descrição | Parâmetros |
|------|-----------|------------|
| `go_to` | Navegar para URL | `url`, `browser`, `headless` |
| `search` | Pesquisar em motor | `query`, `engine` (google/bing/duckduckgo/yandex) |
| `back` | Voltar | — |
| `forward` | Avançar | — |
| `reload` | Recarregar página | — |
| `get_url` | Obter URL atual | — |
| `get_text` | Obter texto da página | — |

### Interação com Elementos

| Ação | Descrição | Parâmetros |
|------|-----------|------------|
| `click` | Clicar em elemento | `selector` (CSS) ou `text` (texto visível) |
| `type` | Digitar texto | `selector`, `text`, `clear_first` |
| `smart_click` | Clicar por descrição | `description` (busca por role/texto/placeholder) |
| `smart_type` | Digitar por descrição | `description`, `text` |
| `scroll` | Rolar página | `direction` (up/down), `amount` (px) |
| `fill_form` | Preencher múltiplos campos | `fields` (dict: selector → valor) |
| `press` | Pressionar tecla | `key` (Enter, Escape, F5, etc.) |

### Ações Avançadas

| Ação | Descrição | Parâmetros |
|------|-----------|------------|
| `upload` | Enviar arquivo para `<input type="file">` | `selector`, `path` |
| `wait` | Aguardar elemento/texto | `selector` ou `text`, `state`, `timeout` |
| `download` | Baixar arquivo via clique | `selector` |
| `script` | Executar workflow multi-step | `steps` (array de objetos de ação) |
| `screenshot` | Salvar screenshot | `path` |

### Gerenciamento de Sessão

| Ação | Descrição |
|------|-----------|
| `new_tab` / `close_tab` | Gerenciamento de abas |
| `switch` / `list_browsers` | Trocar entre navegadores |
| `close` / `close_all` | Fechar sessões |

---

## Parâmetros Globais

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `browser` | STRING | `chrome`, `edge`, `firefox`, `opera`, `operagx`, `brave`, `vivaldi`, `safari` |
| `headless` | BOOLEAN | `true` = navegador invisível (scraping), `false` = visível (default) |

---

## Exemplos de Uso

### 1. Abrir um site e extrair texto

```json
{
  "action": "go_to",
  "url": "https://example.com",
  "browser": "chrome"
}
```

```json
{
  "action": "get_text"
}
```

### 2. Pesquisar no Google

```json
{
  "action": "search",
  "query": "playwright automation python",
  "engine": "google"
}
```

### 3. Clicar em elemento por texto

```json
{
  "action": "click",
  "text": "Aceitar todos"
}
```

### 4. Clicar em elemento por seletor CSS

```json
{
  "action": "click",
  "selector": "button[type='submit']"
}
```

### 5. Digitar em campo de busca

```json
{
  "action": "type",
  "selector": "input[name='q']",
  "text": "playwright documentation",
  "clear_first": true
}
```

### 6. Smart Click (busca inteligente)

```json
{
  "action": "smart_click",
  "description": "botão de login"
}
```

### 7. Preencher formulário completo

```json
{
  "action": "fill_form",
  "fields": {
    "input[name='nome']": "João Silva",
    "input[name='email']": "joao@email.com",
    "input[name='telefone']": "(11) 99999-9999",
    "textarea[name='mensagem']": "Olá, gostaria de um orçamento."
  }
}
```

### 8. Upload de arquivo

```json
{
  "action": "upload",
  "selector": "input[type='file']",
  "path": "C:/Users/faely/Documents/foto.jpg"
}
```

### 9. Aguardar elemento aparecer

```json
{
  "action": "wait",
  "selector": "#resultado-busca",
  "state": "visible",
  "timeout": 15000
}
```

### 10. Aguardar texto aparecer

```json
{
  "action": "wait",
  "text": "Pagamento aprovado",
  "timeout": 30000
}
```

### 11. Download de arquivo

```json
{
  "action": "download",
  "selector": "a[href$='.pdf']"
}
```

### 12. Rolar página

```json
{
  "action": "scroll",
  "direction": "down",
  "amount": 800
}
```

### 13. Pressionar tecla

```json
{
  "action": "press",
  "key": "Enter"
}
```

### 14. Screenshot

```json
{
  "action": "screenshot",
  "path": "C:/Users/faely/Desktop/page.png"
}
```

### 15. Scraping invisível (headless)

```json
{
  "action": "go_to",
  "url": "https://quotes.toscrape.com",
  "headless": true
}
```

---

## Exemplos de Script Multi-Step

### Upload de vídeo no TikTok

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://www.tiktok.com/upload"},
    {"action": "wait", "selector": "input[type=file]", "timeout": 15000},
    {"action": "upload", "selector": "input[type=file]", "path": "C:/Videos/video.mp4"},
    {"action": "wait", "selector": "textarea", "timeout": 15000},
    {"action": "type", "selector": "textarea", "text": "Meu vídeo incrível #viral"},
    {"action": "click", "text": "Post"}
  ]
}
```

### Login + ação em site

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://example.com/login"},
    {"action": "wait", "selector": "input[name='email']", "timeout": 10000},
    {"action": "type", "selector": "input[name='email']", "text": "usuario@email.com"},
    {"action": "type", "selector": "input[name='password']", "text": "minha_senha"},
    {"action": "click", "selector": "button[type='submit']"},
    {"action": "wait", "text": "Bem-vindo", "timeout": 10000},
    {"action": "get_text"}
  ]
}
```

### Pesquisar e extrair resultados do Google

```json
{
  "action": "script",
  "steps": [
    {"action": "search", "query": "preço do dólar hoje", "engine": "google"},
    {"action": "wait", "selector": "#search", "timeout": 10000},
    {"action": "get_text"}
  ]
}
```

### Enviar pergunta para site de LLM e pegar resposta

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://chat.openai.com"},
    {"action": "wait", "selector": "textarea", "timeout": 20000},
    {"action": "type", "selector": "textarea", "text": "O que é inteligência artificial?"},
    {"action": "press", "key": "Enter"},
    {"action": "wait", "text": "Inteligência artificial é", "timeout": 30000},
    {"action": "get_text"}
  ]
}
```

### Navegar em e-commerce e adicionar ao carrinho

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://www.amazon.com.br"},
    {"action": "wait", "selector": "#twotabsearchtextbox", "timeout": 10000},
    {"action": "type", "selector": "#twotabsearchtextbox", "text": "fone de ouvido bluetooth"},
    {"action": "press", "key": "Enter"},
    {"action": "wait", "selector": "[data-component-type='s-search-result']", "timeout": 10000},
    {"action": "click", "selector": "[data-component-type='s-search-result'] h2 a"},
    {"action": "wait", "selector": "#add-to-cart-button", "timeout": 10000},
    {"action": "click", "selector": "#add-to-cart-button"},
    {"action": "get_text"}
  ]
}
```

### Preencher formulário de contato

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://example.com/contato"},
    {"action": "wait", "selector": "form", "timeout": 10000},
    {"action": "fill_form", "fields": {
      "input[name='nome']": "Rafael",
      "input[name='email']": "rafael@email.com",
      "input[name='assunto']": "Orçamento",
      "textarea[name='mensagem']": "Gostaria de um orçamento para site."
    }},
    {"action": "click", "selector": "button[type='submit']"},
    {"action": "wait", "text": "Mensagem enviada", "timeout": 10000}
  ]
}
```

### Scraping de dados com headless

```json
{
  "action": "script",
  "steps": [
    {"action": "go_to", "url": "https://quotes.toscrape.com", "headless": true},
    {"action": "wait", "selector": ".quote", "timeout": 10000},
    {"action": "get_text"}
  ]
}
```

---

## Navegadores Suportados

| Navegador | Engine | Perfil Real | Comando |
|-----------|--------|-------------|---------|
| Chrome | Chromium | ✅ | `browser: "chrome"` |
| Edge | Chromium | ✅ | `browser: "edge"` |
| Firefox | Firefox | ✅ | `browser: "firefox"` |
| Opera | Chromium | ✅ | `browser: "opera"` |
| Opera GX | Chromium | ✅ | `browser: "operagx"` |
| Brave | Chromium | ✅ | `browser: "brave"` |
| Vivaldi | Chromium | ✅ | `browser: "vivaldi"` |
| Safari | WebKit | ✅ | `browser: "safari"` |

---

## Comportamento do Perfil

- O Playwright tenta usar o **perfil real** do navegador (onde você está logado).
- Se o perfil estiver bloqueado (navegador aberto), cria um perfil dedicado em `~/.sirius_profiles/`.
- O modo `headless` sempre usa perfil dedicado (não conflita com navegador aberto).

---

## Dicas para a IA

1. **Use `smart_click` e `smart_type`** quando não souber o seletor CSS exato.
2. **Use `wait`** antes de interagir com elementos que demoram para carregar.
3. **Use `script`** para ações sequenciais — evita overhead de múltiplas chamadas.
4. **Use `headless: true`** para scraping; `headless: false` (default) para automação visível.
5. **Use `get_text`** para extrair conteúdo da página e processar com LLM.
6. **Use `fill_form`** para preencher formulários complexos em uma única chamada.
