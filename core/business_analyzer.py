import json
import time
from pathlib import Path

from google import genai
from google.api_core.exceptions import GoogleAPIError, ServiceUnavailable
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
PROSPECTS_FILE = MEMORY_DIR / "business_prospects.json"
BUSINESS_PROFILE_FILE = CONFIG_DIR / "user_profile_business.json"
from core.config_loader import get_secret
from core.scoring_engine import calculate_purchase_potential, _is_large_company, _estimate_business_size


def _get_api_key() -> str:
    return get_secret("gemini_api_key", "")


def load_business_profile():
    if BUSINESS_PROFILE_FILE.exists():
        try:
            with open(BUSINESS_PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Business Analyzer] Erro ao carregar perfil: {e}")
    return {}


def _call_with_retry(client, model, contents, config, max_retries=3, base_delay=2):
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except ServiceUnavailable:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[Business Analyzer] Gemini 503 (tentativa {attempt+1}/{max_retries}), "
                  f"repetindo em {delay}s...")
            time.sleep(delay)


def analyze_all_businesses():
    api_key = _get_api_key()
    if not api_key:
        print("[Business Analyzer] Erro: Gemini API Key não encontrada.")
        return 0

    profile = load_business_profile()
    if not profile:
        print("[Business Analyzer] Perfil de prospecção não encontrado, usando padrões.")
        profile = {"state": "SP"}

    if not PROSPECTS_FILE.exists():
        print("[Business Analyzer] Nenhum prospect encontrado para análise.")
        return 0

    try:
        with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
            businesses = json.load(f)
    except Exception as e:
        print(f"[Business Analyzer] Erro ao carregar prospects: {e}")
        return 0

    exclude_large = profile.get("exclude_large_companies", True)
    unanalyzed = [b for b in businesses if b.get("site_check") and "analysis" not in b]
    if exclude_large:
        filtered = [b for b in unanalyzed if not _is_large_company(b)]
        if len(filtered) < len(unanalyzed):
            print(f"[Business Analyzer] Excluídas {len(unanalyzed) - len(filtered)} empresas de grande porte da análise")
        unanalyzed = filtered
    if not unanalyzed:
        print("[Business Analyzer] Todas as empresas já foram analisadas.")
        return 0

    print(f"[Business Analyzer] Analisando {len(unanalyzed)} empresas via Gemini API...")

    client = genai.Client(api_key=api_key)
    analyzed_count = 0

    for biz in unanalyzed:
        try:
            name = biz.get("name", "Desconhecida")
            category = biz.get("category", "Não informada")
            address = biz.get("address", "")
            rating = biz.get("rating", "")
            reviews = biz.get("reviews", "")
            has_website = biz.get("has_website", False)
            site_check = biz.get("site_check", {})
            site_quality = site_check.get("quality", "unknown") if site_check else "none"
            site_title = site_check.get("title", "") if site_check else ""
            has_viewport = site_check.get("has_viewport", False) if site_check else False
            has_analytics = site_check.get("has_analytics", False) if site_check else False
            has_whatsapp = site_check.get("has_whatsapp", False) if site_check else False
            load_time = site_check.get("load_time_ms", 0) if site_check else 0
            site_error = site_check.get("error", "") if site_check else ""

            local_score = calculate_purchase_potential(biz)

            prompt = f"""
Você é o motor de inteligência do Sirius, um assistente virtual para prospecção de clientes.
Sua tarefa é analisar a empresa descrita abaixo e determinar o POTENCIAL DE COMPRA DE UM SITE.

--- PERFIL DO USUÁRIO (prospector) ---
Estado Alvo: {profile.get('state', 'SP')}
Observações: {profile.get('notes', 'Foco em pequenas e médias empresas')}
Excluir grandes empresas: {'Sim' if profile.get('exclude_large_companies', True) else 'Não'}

--- EMPRESA ---
Nome: {name}
Categoria: {category}
Endereço: {address}
Avaliação: {rating}
Número de Avaliações: {reviews}

--- PRESENÇA DIGITAL ---
Possui site: {'Sim' if has_website else 'Não'}
Qualidade do site (se existir): {site_quality}
Título do site: {site_title}
Possui viewport (responsivo): {'Sim' if has_viewport else 'Não'}
Tem Analytics: {'Sim' if has_analytics else 'Não'}
Tem WhatsApp: {'Sim' if has_whatsapp else 'Não'}
Tempo de carregamento: {load_time}ms
Erro ao acessar site: {site_error}

--- SCORE PRÉ-CALCULADO (referência) ---
Score calculado objetivamente: {local_score}
Este score foi calculado por um motor de regras baseado nos dados objetivos acima.

--- INSTRUÇÕES DE RETORNO ---
Responda APENAS com um objeto JSON válido contendo exatamente as seguintes chaves (em português brasileiro):
- "purchase_potential": Use o score pré-calculado ({local_score}) como base. Você pode ajustar em até ±5 pontos se houver um contexto forte não capturado pelas regras objetivas. Mantenha como inteiro de 0 a 100.
- "reason": Uma explicação curta (1 frase) do motivo do score. Mencione se é uma empresa de pequeno ou grande porte, se tem site, e qual a qualidade dele.
- "recommended_approach": Sugestão de abordagem comercial personalizada para o porte da empresa (ex: pequeno prestador de serviço regional → "Oferecer site institucional simples com WhatsApp", empresa média → "Site profissional com blog e agendamento online", grande empresa → vazio).
- "red_flags": Lista de possíveis red flags. INCLUA "Empresa de grande porte, baixa chance de conversão" se a empresa parecer grande. INCLUA "Site já é bom, difícil vender upgrade" se o site for de qualidade boa. Deixe vazio se não houver.
- "category": A categoria classificada do negócio (ex: "Restaurante", "Salão de Beleza", "Oficina Mecânica", "Clínica", "Loja", "Serviços", etc). Use os dados disponíveis para classificar.
- "business_size": O porte estimado da empresa: "pequena", "media", ou "grande". Use o número de avaliações como referência (poucas avaliações = pequena, muitas = grande).

CRITÉRIOS DE ANÁLISE:
- Pequenas empresas regionais, prestadores de serviço, e negócios com POUCAS avaliações (menos de 20) devem ter ALTO potencial
- Empresas SEM SITE devem ter prioridade MÁXIMA
- Empresas com WHATSAPP mostram interesse digital e devem ser priorizadas
- Empresas de GRANDE PORTE (muitas avaliações, nome com "Grupo", "S/A", "Matriz") devem ter BAIXÍSSIMO potencial
- Empresas com site de qualidade "bom" já têm presença digital e menor potencial

Importante: Responda estritamente o JSON sem tags markdown adicionais (como ```json) ou qualquer outro texto pré/pós JSON.
"""
            response = _call_with_retry(
                client, "gemini-2.5-flash", prompt,
                types.GenerateContentConfig(response_mime_type="application/json")
            )

            raw_text = response.text.strip()
            analysis_data = json.loads(raw_text)

            gemini_score = analysis_data.get("purchase_potential", local_score)
            if abs(gemini_score - local_score) > 5:
                print(f"[Business Analyzer] Ajuste: {name} - Gemini deu {gemini_score}, usado score local {local_score}")
                analysis_data["purchase_potential"] = local_score
            else:
                analysis_data["purchase_potential"] = gemini_score

            biz["analysis"] = analysis_data
            analyzed_count += 1
            print(f"[Business Analyzer] Analisada: {name} - Potencial: {analysis_data.get('purchase_potential')}%")

            try:
                with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(businesses, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"[Business Analyzer] Erro ao salvar progresso após '{name}': {e}")

        except ServiceUnavailable as e:
            print(f"[Business Analyzer] Gemini sobrecarregado ao analisar '{name}' "
                  f"(esgotadas tentativas). Pulando. Erro: {e}")
        except GoogleAPIError as e:
            print(f"[Business Analyzer] Erro da API Gemini ao analisar '{name}': {e}")
        except json.JSONDecodeError as e:
            print(f"[Business Analyzer] Erro ao decodificar JSON do Gemini para '{name}': {e}")
        except Exception as e:
            print(f"[Business Analyzer] Erro inesperado ao analisar '{name}': {e}")

    if analyzed_count > 0:
        print(f"[Business Analyzer] Salvas {analyzed_count} análises no total!")

    return analyzed_count


if __name__ == "__main__":
    analyze_all_businesses()
