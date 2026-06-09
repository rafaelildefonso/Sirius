# actions/apply_assist.py
import json
from pathlib import Path
from google import genai
from google.genai import types

from core.config_loader import get_secret

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
PROFILE_FILE = CONFIG_DIR / "user_profile.json"


def _get_api_key() -> str:
    return get_secret("gemini_api_key", "")

def apply_assist(parameters: dict, player=None, speak=None) -> str:
    """Generates tailored cover letters, resume adjustment advice, or interview prep based on user profile and a job."""
    params = parameters or {}
    job_title = params.get("job_title", "").strip()
    company = params.get("company", "").strip()
    job_desc = params.get("job_description", "").strip()
    mode = params.get("mode", "cover_letter").lower().strip()
    
    if not job_title or not job_desc:
        # Try to fallback to the currently selected job in the UI
        if player and hasattr(player, "_win") and hasattr(player._win, "job_radar"):
            selected = player._win.job_radar._selected_job
            if selected:
                job_title = selected.get("title", job_title)
                company = selected.get("company", company)
                job_desc = selected.get("description", job_desc)
                
    if not job_title or not job_desc:
        return "Por favor, forneça o título e a descrição da vaga, ou selecione uma vaga no painel do radar."
        
    api_key = _get_api_key()
    if not api_key:
        return "API Key do Gemini não configurada."
        
    # Load user profile
    profile = {}
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except:
            pass
            
    if not profile:
        return "Perfil do candidato não encontrado ou vazio. Configure o seu perfil primeiro."
        
    client = genai.Client(api_key=api_key)
    
    if mode == "cover_letter":
        prompt = f"""
Você é um especialista em recrutamento técnico de ponta. Escreva uma Carta de Apresentação (Cover Letter) extremamente profissional, persuasiva e personalizada para a vaga abaixo, baseando-se estritamente no perfil do candidato fornecido. A carta deve ser humana, autêntica e focar em resultados tangíveis.

--- PERFIL DO CANDIDATO ---
Nome: {profile.get('full_name')}
Cargo atual: {profile.get('title')}
Mini bio: {profile.get('resume_summary')}
Skills: {', '.join(profile.get('skills', []))}
Anos de experiência: {profile.get('experience_years')} anos

--- VAGA ---
Vaga: {job_title} na empresa {company}
Descrição:
{job_desc}

--- INSTRUÇÕES ---
Escreva em Português Brasileiro (ou Inglês, caso a descrição da vaga esteja em inglês).
A resposta deve conter APENAS a carta de apresentação pronta para ser enviada, sem comentários adicionais seus.
"""
    elif mode == "resume_tailor":
        prompt = f"""
Você é um recrutador técnico experiente. Analise o perfil do candidato e a descrição da vaga a seguir e dê conselhos específicos de como adaptar o currículo do candidato para aumentar o Match do ATS (Applicant Tracking System) para essa vaga específica.

--- PERFIL DO CANDIDATO ---
Habilidades atuais: {', '.join(profile.get('skills', []))}
Mini bio: {profile.get('resume_summary')}

--- VAGA ---
Vaga: {job_title} na empresa {company}
Descrição:
{job_desc}

--- INSTRUÇÕES ---
Identifique quais palavras-chave cruciais da vaga estão faltando nas habilidades do candidato.
Sugira como reescrever a mini bio ou destacar projetos para ressoar melhor com essa vaga.
Seja conciso e direto em pontos (bullets).
"""
    else:  # interview_prep
        prompt = f"""
Aja como um tech lead simulando uma entrevista técnica de emprego. Com base no perfil do candidato e na vaga a seguir, gere as 3 principais perguntas técnicas que provavelmente seriam feitas para ele nesta entrevista, seguidas de dicas de como ele deve responder de forma a destacar suas forças.

--- PERFIL DO CANDIDATO ---
Skills do candidato: {', '.join(profile.get('skills', []))}

--- VAGA ---
Vaga: {job_title} na empresa {company}
Descrição:
{job_desc}
"""
    
    try:
        if speak:
            speak("Processando sua solicitação de assistência com a inteligência artificial, aguarde um instante...")
            
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        result = response.text.strip()
        
        # Copy to clipboard if it's a cover letter
        if mode == "cover_letter":
            try:
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    clipboard = app.clipboard()
                    clipboard.setText(result)
                    result += "\n\n[SIRIUS: Carta de apresentação copiada para a área de transferência com sucesso!]"
            except Exception as e:
                print(f"[Apply Assist] Erro ao copiar para o clipboard: {e}")
                
        return result
        
    except Exception as e:
        return f"Falha na geração com Gemini: {e}"
