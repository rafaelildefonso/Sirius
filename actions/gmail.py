from core.cache import api_cache
from core.google_auth import get_google_service

def gmail_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Interface para o Gmail.
    Parâmetros:
        action: "list_emails" | "search_emails" | "read_email"
        query: Termo de busca (ex: "is:unread", "from:jose")
        count: int (padrão: 5)
    """
    action = parameters.get("action", "list_emails").lower()
    if action == "list": action = "list_emails"
    if action == "search": action = "search_emails"
    if action == "read": action = "read_email"

    query = parameters.get("query", "")
    count = int(parameters.get("count", 5))

    try:
        service = get_google_service('gmail', 'v1')
        if not service:
            return "Desculpe, não consegui acessar sua conta do Gmail."

        if action in ("list_emails", "search_emails"):
            if action == "list_emails" and not query:
                query = "label:INBOX"

            cache_key = f"gmail:list:{query}:{count}"
            cached = api_cache.get(cache_key)
            if cached is not None:
                return cached
            
            results = service.users().messages().list(userId='me', q=query, maxResults=count).execute()
            messages = results.get('messages', [])

            if not messages:
                api_cache.set(cache_key, f"Nenhum e-mail encontrado para a busca: {query}", ttl=120)
                return f"Nenhum e-mail encontrado para a busca: {query}"

            res = "E-mails recentes:\n"
            for msg in messages:
                msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['Subject', 'From']).execute()
                headers = msg_data.get('payload', {}).get('headers', [])
                
                subject = "Sem Assunto"
                sender = "Desconhecido"
                for h in headers:
                    if h['name'] == 'Subject':
                        subject = h['value']
                    if h['name'] == 'From':
                        sender = h['value']
                
                res += f"- De: {sender}\n  Assunto: {subject}\n"
            
            api_cache.set(cache_key, res, ttl=120)
            return res

        elif action == "read_email":
            results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
            messages = results.get('messages', [])
            
            if not messages:
                return "Não encontrei nenhum e-mail para ler."
            
            msg_id = messages[0]['id']
            cache_key = f"gmail:read:{msg_id}"
            cached = api_cache.get(cache_key)
            if cached is not None:
                return cached

            msg_data = service.users().messages().get(userId='me', id=msg_id).execute()
            snippet = msg_data.get('snippet', '')
            result = f"Conteúdo do e-mail:\n{snippet}..."
            api_cache.set(cache_key, result, ttl=300)
            return result

        return f"Ação '{action}' não reconhecida no Gmail."

    except Exception as e:
        print(f"[Gmail] Erro: {e}")
        return f"Ocorreu um erro ao acessar seus e-mails: {e}"
