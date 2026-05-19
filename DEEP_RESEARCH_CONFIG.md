# Configuração do Deep Research

O módulo de pesquisa profunda (deep_research) agora suporta múltiplas APIs de busca para encontrar leads de negócios locais. Todas as APIs são **opcionais** - o sistema funcionará com as soluções gratuitas se as APIs pagas não estiverem configuradas.

## APIs Suportadas

### 1. Tavily API (Opcional)
- **Prioridade**: Alta (primeira estratégia de busca)
- **Vantagens**: Busca avançada com filtro de localização nativo
- **Como obter**: 
  1. Acesse https://tavily.com/
  2. Crie uma conta gratuita
  3. Obtenha sua API key no dashboard
- **Configuração**: Adicione ao `config/api_keys.json`:
  ```json
  {
    "tavily_api_key": "sua_chave_aqui"
  }
  ```

### 2. SerpAPI (Opcional)
- **Prioridade**: Alta (segunda estratégia de busca)
- **Vantagens**: Acesso ao Google Places e Google Maps
- **Como obter**:
  1. Acesse https://serpapi.com/
  2. Crie uma conta (plano gratuito disponível)
  3. Obtenha sua API key
- **Configuração**: Adicione ao `config/api_keys.json`:
  ```json
  {
    "serpapi_key": "sua_chave_aqui"
  }
  ```

### 3. Gemini API (Opcional)
- **Prioridade**: Média (terceira estratégia de busca)
- **Vantagens**: Google Search integrado ao Gemini
- **Como obter**:
  1. Acesse https://aistudio.google.com/
  2. Crie um projeto e obtenha a API key
- **Configuração**: Já deve estar configurada como `gemini_api_key` no `config/api_keys.json`

### 4. DuckDuckGo (Gratuito)
- **Prioridade**: Fallback (sempre disponível)
- **Vantagens**: Gratuito, não requer configuração
- **Limitações**: Menos preciso para buscas locais

## Exemplo de Configuração Completa

Edite o arquivo `config/api_keys.json`:

```json
{
  "openrouter_api_key": "sua_chave_openrouter",
  "gemini_api_key": "sua_chave_gemini",
  "tavily_api_key": "sua_chave_tavily",
  "serpapi_key": "sua_chave_serpapi"
}
```

## Pipeline de Busca

O sistema tenta as estratégias nesta ordem:

1. **Tavily** (se configurado) → 20 resultados com filtro de localização
2. **SerpAPI** (se configurado) → 20 resultados
3. **Gemini Search** (se configurado) → 15 resultados
4. **DuckDuckGo** (sempre disponível) → 15 resultados

## Instalação de Dependências

As novas bibliotecas já foram adicionadas ao `requirements.txt`. Para instalar:

```bash
pip install -r requirements.txt
```

Ou instale individualmente:

```bash
pip install tavily-python
pip install google-search-results
```

## Melhorias Implementadas

- ✅ Múltiplas estratégias de busca com fallback automático
- ✅ Queries inteligentes com variações
- ✅ Filtros avançados de domínios (exclui dicionários, redes sociais, etc.)
- ✅ Verificação de localização (telefone, endereço, menções à cidade)
- ✅ Avaliação de leads com score de confiança de localização
- ✅ Deduplicação de resultados
- ✅ Aumento de resultados (até 30 por busca)
- ✅ Ordenação por confiança combinada (relevância + localização)

## Uso

O deep research funciona da mesma forma. O sistema usará automaticamente as APIs configuradas:

```
"faça uma pesquisa de freelance para mim"
→ O sistema perguntará competências, público-alvo e região
→ Executará a busca usando todas as APIs disponíveis
→ Retornará leads ordenados por relevância e localização
```
