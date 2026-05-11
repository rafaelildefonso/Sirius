from datetime import datetime, timedelta
from core.google_auth import get_google_service

def google_calendar(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Interface para o Google Calendar.
    Parâmetros:
        action: "list_events" | "create_event"
        date: string YYYY-MM-DD (opcional, padrão: hoje)
    """
    action = parameters.get("action", "list_events").lower()
    if action == "list": action = "list_events"
    if action == "create": action = "create_event"
    
    date_str = parameters.get("date", datetime.now().strftime("%Y-%m-%d"))

    try:
        service = get_google_service('calendar', 'v3')
        if not service:
            return "Desculpe, não consegui acessar sua conta do Google."

        if action == "list_events":
            # Formata a data para o formato RFC3339
            try:
                start_dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                # Fallback para "hoje", "amanhã" se o planner enviar algo assim
                if "hoje" in date_str.lower():
                    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                elif "amanhã" in date_str.lower():
                    start_dt = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            end_dt = start_dt + timedelta(days=1)
            
            time_min = start_dt.isoformat() + 'Z'
            time_max = end_dt.isoformat() + 'Z'

            events_result = service.events().list(
                calendarId='primary', 
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])

            if not events:
                return f"Você não tem nenhum compromisso agendado para {date_str}."

            res = f"Compromissos para {date_str}:\n"
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                # Formata a hora se houver
                if 'T' in start:
                    time_part = start.split('T')[1].split('-')[0][:5]
                    res += f"- {time_part}: {event['summary']}\n"
                else:
                    res += f"- [Dia Todo]: {event['summary']}\n"
            
            return res

        elif action == "create_event":
            # Implementação básica de criação (opcional agora, mas boa para ter)
            summary = parameters.get("summary", "Novo Evento")
            start_time = parameters.get("start_time") # Esperado: YYYY-MM-DD HH:MM
            
            if not start_time:
                return "Preciso de um horário para criar o evento."

            event = {
                'summary': summary,
                'start': {'dateTime': f"{start_time.replace(' ', 'T')}:00Z"},
                'end': {'dateTime': f"{start_time.replace(' ', 'T')}:00Z"}, # Duração zero ou tratar
            }
            
            event = service.events().insert(calendarId='primary', body=event).execute()
            return f"Evento criado: {event.get('htmlLink')}"

        return f"Ação '{action}' não reconhecida no Google Calendar."

    except Exception as e:
        print(f"[GoogleCalendar] Erro: {e}")
        return f"Ocorreu um erro ao acessar o calendário: {e}"
