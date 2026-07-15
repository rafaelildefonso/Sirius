from datetime import datetime, timedelta
from core.notion_auth import get_notion_client
from core.cache import api_cache
import requests


def notion_calendar(
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
    if action in ("list_databases", "list_dbs"):
        action = "list_databases"
    if action in ("complete", "mark", "done", "check"):
        action = "complete_event"

    notion_client = get_notion_client()
    if not notion_client:
        return "Desculpe, não consegui acessar sua conta do Notion. Configure o token de API do Notion nas configurações."

    try:
        if action == "list_events":
            return _list_notion_events(parameters, notion_client)
        elif action == "create_event":
            return _create_notion_event(parameters, notion_client)
        elif action == "list_databases":
            return _list_notion_databases(notion_client)
        elif action == "complete_event":
            return _complete_notion_event(parameters, notion_client)
        else:
            return f"Ação '{action}' não reconhecida no Notion Calendar."

    except Exception as e:
        print(f"[NotionCalendar] Erro: {e}")
        return f"Ocorreu um erro ao acessar o calendário do Notion: {e}"


def _list_notion_events(parameters: dict, notion_client: dict) -> str:
    database_id = parameters.get("database_id")
    if not database_id:
        database_id = _get_default_database_id()
        if not database_id:
            return "Por favor, forneça o ID do banco de dados do Notion para usar como calendário."

    data_source_id = parameters.get("data_source_id")
    if not data_source_id:
        try:
            data_source_id = _get_data_source_id(database_id, notion_client)
        except (requests.RequestException, ValueError, KeyError) as e:
            return f"Erro ao acessar o banco de dados do Notion: {e}"

    days = parameters.get("days")
    date_str = parameters.get("date")

    local_tz = datetime.now().astimezone().tzinfo

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

    try:
        schema = _get_data_source_schema(data_source_id, notion_client)
    except Exception as e:
        return f"Erro ao obter schema do data source: {e}"

    date_prop = _find_date_property(schema)
    if not date_prop:
        return "Nenhuma propriedade de data encontrada neste database."

    url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"

    filter_conditions = {
        "and": [
            {
                "property": date_prop,
                "date": {
                    "on_or_after": start_dt.strftime("%Y-%m-%d")
                }
            },
            {
                "property": date_prop,
                "date": {
                    "on_or_before": end_dt.strftime("%Y-%m-%d")
                }
            }
        ]
    }

    payload = {
        "filter": filter_conditions,
        "sorts": [
            {
                "property": date_prop,
                "direction": "ascending"
            }
        ]
    }

    try:
        response = requests.post(url, headers=notion_client, json=payload)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response is not None else "N/A"
        body = e.response.text if e.response is not None else "N/A"
        print(f"[NotionCalendar] Query error: {body}")
        return f"Erro ao consultar o banco de dados do Notion (HTTP {status}): {body}"

    results = data.get("results", [])

    if not results:
        if delta_days == 1:
            return f"Você não tem nenhum compromisso agendado para {start_dt.strftime('%Y-%m-%d')}."
        return f"Você não tem nenhum compromisso agendado entre {start_dt.strftime('%Y-%m-%d')} e {end_dt.strftime('%Y-%m-%d')}."

    if delta_days == 1:
        res = f"Compromissos para {start_dt.strftime('%Y-%m-%d')}:\n"
    else:
        res = f"Compromissos de {start_dt.strftime('%Y-%m-%d')} a {end_dt.strftime('%Y-%m-%d')}:\n"

    for page in results:
        title = "Sem título"
        if page.get("properties"):
            props = page["properties"]
            for prop_value in props.values():
                if prop_value.get("type") == "title":
                    title_array = prop_value.get("title", [])
                    if title_array:
                        title = "".join(t.get("plain_text", "") for t in title_array)
                    break

        time_str = ""
        if page.get("properties"):
            for prop_value in page["properties"].values():
                if prop_value.get("type") == "date":
                    date_info = prop_value.get("date")
                    if date_info and date_info.get("start"):
                        start = date_info["start"]
                        try:
                            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                            if "T" in start:
                                time_str = dt.strftime("%H:%M")
                            else:
                                time_str = "[Dia Todo]"
                        except Exception:
                            time_str = start
                    break

        pid = page.get("id", "")[:8]
        if time_str:
            res += f"- ({pid}) {time_str}: {title}\n"
        else:
            res += f"- ({pid}) {title}\n"

    return res


def _create_notion_event(parameters: dict, notion_client: dict) -> str:
    database_id = parameters.get("database_id")
    if not database_id:
        database_id = _get_default_database_id()
        if not database_id:
            return "Por favor, forneça o ID do banco de dados do Notion para usar como calendário."

    data_source_id = parameters.get("data_source_id")
    if not data_source_id:
        try:
            data_source_id = _get_data_source_id(database_id, notion_client)
        except (requests.RequestException, ValueError, KeyError) as e:
            return f"Erro ao acessar o banco de dados do Notion: {e}"

    summary = parameters.get("summary", "Novo Evento")
    start_raw = parameters.get("start_time") or parameters.get("start")
    end_raw = parameters.get("end_time") or parameters.get("end")

    if not start_raw:
        return "Preciso de um horário para criar o evento."

    try:
        if ' ' in start_raw:
            start_dt = datetime.strptime(start_raw, "%Y-%m-%d %H:%M")
        else:
            start_dt = datetime.strptime(start_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        return "Formato de data/hora inválido. Use YYYY-MM-DD HH:MM ou YYYY-MM-DDTHH:MM"

    if end_raw:
        try:
            if ' ' in end_raw:
                end_dt = datetime.strptime(end_raw, "%Y-%m-%d %H:%M")
            else:
                end_dt = datetime.strptime(end_raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = start_dt + timedelta(hours=1)

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    try:
        schema = _get_data_source_schema(data_source_id, notion_client)
    except Exception as e:
        return f"Erro ao obter schema do data source: {e}"

    date_prop = _find_date_property(schema) or "Date"
    title_prop = _find_title_property(schema) or "Name"

    url = "https://api.notion.com/v1/pages"

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": {
            title_prop: {
                "type": "title",
                "title": [
                    {"type": "text", "text": {"content": summary}}
                ]
            },
            date_prop: {
                "type": "date",
                "date": {
                    "start": start_iso,
                    "end": end_iso
                }
            }
        }
    }

    try:
        response = requests.post(url, headers=notion_client, json=payload)
        response.raise_for_status()
        data = response.json()
        page_url = data.get("url", "")
        return f"Evento criado no Notion: {page_url}" if page_url else "Evento criado no Notion."
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response is not None else "N/A"
        body = e.response.text if e.response is not None else "N/A"
        print(f"[NotionCalendar] Create error: {body}")
        return f"Erro ao criar evento no Notion (HTTP {status}): {body}"


def _complete_notion_event(parameters: dict, notion_client: dict) -> str:
    database_id = parameters.get("database_id")
    if not database_id:
        database_id = _get_default_database_id()
        if not database_id:
            return "Por favor, forneça o ID do banco de dados do Notion para usar como calendário."

    data_source_id = parameters.get("data_source_id")
    if not data_source_id:
        try:
            data_source_id = _get_data_source_id(database_id, notion_client)
        except (requests.RequestException, ValueError, KeyError) as e:
            return f"Erro ao acessar o banco de dados do Notion: {e}"

    try:
        schema = _get_data_source_schema(data_source_id, notion_client)
    except Exception as e:
        return f"Erro ao obter schema do data source: {e}"

    checkbox_prop = next((n for n, p in schema.items() if p.get("type") == "checkbox"), None)
    status_prop = next((n for n, p in schema.items() if p.get("type") == "status"), None)
    select_prop = next((n for n, p in schema.items() if p.get("type") == "select"), None)

    page_id = parameters.get("page_id")
    if not page_id:
        search_title = parameters.get("search_title")
        if not search_title:
            return "Forneça o 'page_id' ou o 'search_title' para localizar o evento."

        date_str = parameters.get("date")
        local_tz = datetime.now().astimezone().tzinfo
        if date_str:
            try:
                start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=local_tz)
            except ValueError:
                start_dt = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_dt = datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=1)

        title_prop = _find_title_property(schema) or "Name"
        query_url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
        query_payload = {
            "filter": {
                "and": [
                    {"property": title_prop, "rich_text": {"contains": search_title}},
                    {"property": _find_date_property(schema) or "Date", "date": {"on_or_after": start_dt.strftime("%Y-%m-%d")}},
                    {"property": _find_date_property(schema) or "Date", "date": {"on_or_before": end_dt.strftime("%Y-%m-%d")}},
                ]
            },
            "page_size": 5,
        }
        try:
            resp = requests.post(query_url, headers=notion_client, json=query_payload)
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except requests.exceptions.RequestException as e:
            status = e.response.status_code if e.response is not None else "N/A"
            body = e.response.text if e.response is not None else "N/A"
            return f"Erro ao buscar evento (HTTP {status}): {body}"

        if not results:
            return f"Nenhum evento encontrado com o título contendo '{search_title}' na data {start_dt.strftime('%Y-%m-%d')}."
        page_id = results[0].get("id")

    _done_keywords = ["done", "complete", "completed", "concluído", "concluido", "feito", "finalizado"]

    update_props = {}
    if checkbox_prop:
        update_props[checkbox_prop] = {"type": "checkbox", "checkbox": True}
    elif status_prop:
        options = [o["name"] for o in schema[status_prop].get("status", {}).get("options", [])]
        match = next((o for o in options if o.lower() in _done_keywords), None)
        if match:
            update_props[status_prop] = {"type": "status", "status": {"name": match}}
        else:
            return f"Propriedade '{status_prop}' encontrada, mas nenhuma opção parece 'concluído'. Opções disponíveis: {', '.join(options)}"
    elif select_prop:
        options = [o["name"] for o in schema[select_prop].get("select", {}).get("options", [])]
        match = next((o for o in options if o.lower() in _done_keywords), None)
        if match:
            update_props[select_prop] = {"type": "select", "select": {"name": match}}
        else:
            return f"Propriedade '{select_prop}' encontrada, mas nenhuma opção parece 'concluído'. Opções disponíveis: {', '.join(options)}"
    else:
        return "Este database não possui propriedade do tipo checkbox, status ou select para marcar como concluído."

    url = f"https://api.notion.com/v1/pages/{page_id}"
    try:
        resp = requests.patch(url, headers=notion_client, json={"properties": update_props})
        resp.raise_for_status()
        return f"Evento marcado como concluído no Notion."
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response is not None else "N/A"
        body = e.response.text if e.response is not None else "N/A"
        print(f"[NotionCalendar] Complete error: {body}")
        return f"Erro ao marcar evento como concluído (HTTP {status}): {body}"


def _list_notion_databases(headers: dict) -> str:
    cache_key = "notion:databases"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "data_source"},
        "page_size": 100,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        status = e.response.status_code if e.response is not None else "N/A"
        body = e.response.text if e.response is not None else "N/A"
        return f"Erro ao buscar databases no Notion (HTTP {status}): {body}"

    results = data.get("results", [])
    if not results:
        return "Nenhum database ou data source encontrado. Verifique se a integração foi compartilhada com algum database em Share -> Add connections."

    seen = {}
    for ds in results:
        parent = ds.get("parent", {})
        db_id = parent.get("database_id", "") if parent.get("type") == "database_id" else ""

        title_parts = ds.get("title") or ds.get("properties", {}).get("title", [])
        if isinstance(title_parts, list):
            name = "".join(t.get("plain_text", "") for t in title_parts if t.get("type") == "text")
        elif isinstance(title_parts, dict):
            name = title_parts.get("title", [{}])[0].get("plain_text", "") if title_parts.get("title") else ""
        else:
            name = ds.get("name", "Sem nome")

        props = ds.get("properties", {})
        has_date = any(v.get("type") == "date" for v in props.values())

        if db_id not in seen:
            seen[db_id] = {"name": name, "has_date": has_date, "ds_ids": []}
        seen[db_id]["ds_ids"].append(ds.get("id", "?"))

    lines = ["[INSTALL] Databases disponíveis no Notion:\n"]
    for db_id, info in seen.items():
        date_tag = "[OK] tem data" if info["has_date"] else "[FAIL] sem data"
        ds_ids = ", ".join(info["ds_ids"])
        lines.append(f"  - {info['name']} ({date_tag})\n    Database ID: {db_id}\n    Data Source ID(s): {ds_ids}\n")

    result = "".join(lines)
    api_cache.set(cache_key, result, ttl=3600)
    return result


def _get_data_source_schema(data_source_id: str, headers: dict) -> dict:
    cache_key = f"notion:schema:{data_source_id}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
    url = f"https://api.notion.com/v1/data_sources/{data_source_id}"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    result = resp.json().get("properties", {})
    api_cache.set(cache_key, result, ttl=3600)
    return result


def _find_date_property(schema: dict) -> str | None:
    for name, prop in schema.items():
        if prop.get("type") == "date":
            return name
    return None


def _find_title_property(schema: dict) -> str | None:
    for name, prop in schema.items():
        if prop.get("type") == "title":
            return name
    return None


def _get_data_source_id(notion_id: str, headers: dict) -> str:
    cache_key = f"notion:dsid:{notion_id}"
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached
    ds_url = f"https://api.notion.com/v1/data_sources/{notion_id}"
    ds_resp = requests.get(ds_url, headers=headers)
    if ds_resp.status_code == 200:
        api_cache.set(cache_key, notion_id, ttl=3600)
        return notion_id

    db_url = f"https://api.notion.com/v1/databases/{notion_id}"
    db_resp = requests.get(db_url, headers=headers)
    if db_resp.status_code == 200:
        data = db_resp.json()
        sources = data.get("data_sources", [])
        if not sources:
            raise ValueError("Database não contém data sources")
        result = sources[0]["id"]
        api_cache.set(cache_key, result, ttl=3600)
        return result

    if ds_resp.status_code == 404 and db_resp.status_code == 404:
        raise ValueError(
            "ID não encontrado pela API do Notion (404). "
            "Verifique se: (1) o ID copiado da URL está correto, "
            "(2) a integração foi compartilhada com o database em Share -> Add connections. "
            "Use a ação 'list_databases' para ver todos os databases disponíveis."
        )
    erro = ds_resp if ds_resp.status_code != 404 else db_resp
    raise ValueError(f"Erro HTTP {erro.status_code} ao acessar Notion: {erro.text}")


def _get_default_database_id() -> str:
    try:
        from core.config_loader import get_notion_creds
        creds = get_notion_creds()
        db_id = creds.get("database_id", "")
        print(f"[NotionCalendar] database_id lido: '{db_id}' (tamanho={len(db_id)})")
        return db_id
    except Exception as e:
        print(f"[NotionCalendar] erro ao ler database_id: {e}")
        return ""
