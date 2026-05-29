# core/job_analyzer.py
import json
import os
import sys
from pathlib import Path
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
JOBS_FILE = MEMORY_DIR / "linkedin_jobs.json"
PROFILE_FILE = CONFIG_DIR / "user_profile.json"
API_KEYS_FILE = CONFIG_DIR / "api_keys.json"

def _get_api_key() -> str:
    try:
        with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("gemini_api_key", "")
    except Exception:
        return ""

def load_user_profile():
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Job Analyzer] Erro ao carregar perfil: {e}")
    return {}

def analyze_all_jobs():
    """Analyzes all new (unanalyzed) jobs in linkedin_jobs.json using Gemini API."""
    api_key = _get_api_key()
    if not api_key:
        print("[Job Analyzer] Erro: Gemini API Key não encontrada.")
        return 0
        
    profile = load_user_profile()
    if not profile:
        print("[Job Analyzer] Erro: Perfil do usuário não encontrado ou vazio.")
        return 0
        
    if not JOBS_FILE.exists():
        print("[Job Analyzer] Erro: Nenhuma vaga encontrada para análise.")
        return 0
        
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except Exception as e:
        print(f"[Job Analyzer] Erro ao carregar vagas: {e}")
        return 0
        
    # Filter unanalyzed jobs
    unanalyzed = [job for job in jobs if "analysis" not in job]
    if not unanalyzed:
        print("[Job Analyzer] Todas as vagas já foram analisadas.")
        return 0
        
    print(f"[Job Analyzer] Analisando {len(unanalyzed)} vagas usando Gemini API...")
    
    # Initialize Gemini client
    client = genai.Client(api_key=api_key)
    analyzed_count = 0
    
    for job in unanalyzed:
        try:
            # Construct analysis prompt
            prompt = f"""
Você é o motor de inteligência do Sirius, um assistente virtual para desenvolvedores de software.
Sua tarefa é analisar a vaga de emprego descrita abaixo e verificar a compatibilidade com o perfil do candidato fornecido.

--- PERFIL DO CANDIDATO ---
Nome: {profile.get('full_name')}
Cargo Pretendido: {profile.get('title')}
Resumo: {profile.get('resume_summary')}
Habilidades (Stacks): {', '.join(profile.get('skills', []))}
Anos de Experiência: {profile.get('experience_years')} anos
Localização de Preferência: {profile.get('preferred_location')}
Expectativa Salarial: {profile.get('salary_expectation')}
Cargos Alvo: {', '.join(profile.get('target_roles', []))}
Palavras-chave a Evitar: {', '.join(profile.get('avoid_keywords', []))}

--- VAGA ---
Título: {job.get('title')}
Empresa: {job.get('company')}
Localização: {job.get('location')}
Descrição da Vaga:
{job.get('description')}

--- INSTRUÇÕES DE RETORNO ---
Responda APENAS com um objeto JSON válido contendo exatamente as seguintes chaves (em português brasileiro):
- "match_score": Um inteiro de 0 a 100 que calcula o nível de compatibilidade. Leve em conta: stack compatível, anos de experiência (se pede júnior/pleno) e tipo de trabalho (remoto vs presencial). Seja realista.
- "summary": Um resumo curto de 1 a 2 sentenças sobre a vaga e stack principal.
- "fit_reason": Por que essa vaga é um bom match (ex: stacks compatíveis, salário, modelo remoto).
- "gap_reason": Onde estão os gaps do candidato para essa vaga (ex: tecnologias que faltam, anos de experiência exigidos além do que o candidato tem).
- "red_flags": Uma lista (array) de possíveis red flags ou pontos de atenção (ex: exige presencial quando o candidato quer remoto, vaga exige tempo de experiência muito alto, modelo PJ abusivo, etc.). Se não houver nenhum, deixe a lista vazia.
- "cover_letter_idea": Uma ideia ou estratégia curta de abordagem para essa vaga (ex: "Destaque sua experiência com FastAPI no currículo...").

Importante: Responda estritamente o JSON sem tags markdown adicionais (como ```json) ou qualquer outro texto pré/pós JSON.
"""
            # Call Gemini
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            raw_text = response.text.strip()
            # Parse JSON
            analysis_data = json.loads(raw_text)
            
            # Apply analysis data to job
            job["analysis"] = analysis_data
            analyzed_count += 1
            print(f"[Job Analyzer] Analisada com sucesso: {job['title']} - Match: {analysis_data.get('match_score')}%")
            
        except Exception as e:
            print(f"[Job Analyzer] Erro ao analisar vaga {job.get('title')}: {e}")
            # If JSON parsing fails or Gemini fails, we skip for now
            continue
            
    # Save back to file
    if analyzed_count > 0:
        try:
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(jobs, f, indent=4, ensure_ascii=False)
            print(f"[Job Analyzer] Salvas {analyzed_count} análises com sucesso!")
        except Exception as e:
            print(f"[Job Analyzer] Erro ao salvar análises: {e}")
            
    return analyzed_count

if __name__ == "__main__":
    analyze_all_jobs()
