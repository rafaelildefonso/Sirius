from datetime import datetime, timedelta, timezone
from core.google_auth import get_google_service


def google_calendar(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    action = parameters.get("action", "list_events").lower()
    if action == "list":
        action = "list_events"
    if action == "create":
        action = "create_event"

    local_tz = datetime.now(timezone.utc).astimezone().tzinfo

    try:
        service = get_google_service('calendar', 'v3')
        if not service:
            return "Desculpe, não consegui acessar sua conta do Google."

        if action == "list_events":
            days = parameters.get("days")
            date_str = parameters.get("date")

            if date_str:
                try:
                    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=local_tz)
                except ValueError:
                    if "hoje" in date_str.lower():
                        start_dt = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
                    elif "amanhã" in date_str.lower():
                        start_dt = (datetime.now(local_tz) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    else:
                        start_dt = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                start_dt = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)

            delta_days = days if days else 1
            end_dt = start_dt + timedelta(days=delta_days)

            time_min = start_dt.astimezone(timezone.utc).isoformat()
            time_max = end_dt.astimezone(timezone.utc).isoformat()

            events_result = service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])

            if not events:
                if delta_days == 1:
                    return f"Você não tem nenhum compromisso agendado para {start_dt.strftime('%Y-%m-%d')}."
                return f"Você não tem nenhum compromisso agendado entre {start_dt.strftime('%Y-%m-%d')} e {end_dt.strftime('%Y-%m-%d')}."

            if delta_days == 1:
                res = f"Compromissos para {start_dt.strftime('%Y-%m-%d')}:\n"
            else:
                res = f"Compromissos de {start_dt.strftime('%Y-%m-%d')} a {end_dt.strftime('%Y-%m-%d')}:\n"

            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                if 'T' in start:
                    time_part = start.split('T')[1].split('-')[0][:5]
                    res += f"- {time_part}: {event['summary']}\n"
                else:
                    res += f"- [Dia Todo]: {event['summary']}\n"

            return res

        elif action == "create_event":
            summary = parameters.get("summary", "Novo Evento")
            start_raw = parameters.get("start_time") or parameters.get("start")

            if not start_raw:
                return "Preciso de um horário para criar o evento."

            if ' ' in start_raw:
                start_iso = start_raw.replace(' ', 'T')
                start_dt = datetime.strptime(start_raw[:16], "%Y-%m-%d %H:%M")
            else:
                start_iso = start_raw
                try:
                    start_dt = datetime.strptime(start_raw[:16], "%Y-%m-%dT%H:%M")
                except ValueError:
                    start_dt = datetime.now(local_tz)

            end_dt = start_dt + timedelta(hours=1)
            offset = local_tz.utcoffset(start_dt)
            total_seconds = int(offset.total_seconds())
            sign = '+' if total_seconds >= 0 else '-'
            hours = abs(total_seconds) // 3600
            minutes = (abs(total_seconds) % 3600) // 60
            tz_str = f"{sign}{hours:02d}:{minutes:02d}"

            event = {
                'summary': summary,
                'start': {'dateTime': f"{start_iso}:00{tz_str}"},
                'end': {'dateTime': f"{end_dt.strftime('%Y-%m-%dT%H:%M')}:00{tz_str}"},
            }

            event = service.events().insert(calendarId='primary', body=event).execute()
            return f"Evento criado: {event.get('htmlLink')}"

        return f"Ação '{action}' não reconhecida no Google Calendar."

    except Exception as e:
        print(f"[GoogleCalendar] Erro: {e}")
        return f"Ocorreu um erro ao acessar o calendário: {e}"
