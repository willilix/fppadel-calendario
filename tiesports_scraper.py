# tiesports_scraper.py
import re
from typing import Dict, Any, Optional, List, Tuple

import requests
from bs4 import BeautifulSoup
from unidecode import unidecode

SUMMARY_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

# O target do "Ver mais" (Masculinos) que tu apanhaste no HTML:
LOAD_MORE_TARGETS = {
    "Masculinos": "repeater_rankings_top_10$ctl00$link_load_more_men",
    # Se apanhares os outros depois, metes aqui:
    # "Femininos": "repeater_rankings_top_10$ctl00$link_load_more_women",
    # "Mistos":    "repeater_rankings_top_10$ctl00$link_load_more_mixed",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Origin": "https://tour.tiesports.com",
    "Referer": SUMMARY_URL,
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode((s or "").strip().lower()))

def _is_searchable_page(html: str) -> bool:
    h = (html or "").lower()
    # na página pesquisável existe o label + botão
    return ("nome/licença" in h or "nome/licenca" in h) and ("filtrar" in h)

def _collect_form_fields(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Recolhe todos os campos do <form>, incluindo __VIEWSTATE, __EVENTVALIDATION, etc.
    """
    form = soup.find("form")
    if not form:
        return {}

    data: Dict[str, str] = {}

    # inputs
    for inp in form.select("input"):
        name = inp.get("name")
        if not name:
            continue

        itype = (inp.get("type") or "").lower()
        if itype in ("submit", "button", "image"):
            continue

        if itype in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                data[name] = inp.get("value", "on")
            continue

        data[name] = inp.get("value", "")

    # selects
    for sel in form.select("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[name] = opt.get("value", "") if opt else ""

    # textareas
    for ta in form.select("textarea"):
        name = ta.get("name")
        if name:
            data[name] = ta.text or ""

    return data

def _find_input_name_by_label(soup: BeautifulSoup, label_contains: str) -> Optional[str]:
    """
    Encontra o atributo 'name' do input associado ao label.
    """
    for lab in soup.find_all("label"):
        txt = lab.get_text(" ", strip=True).lower()
        if label_contains.lower() in txt:
            # label for="id"
            for_attr = lab.get("for")
            if for_attr:
                inp = soup.find(id=for_attr)
                if inp and inp.get("name"):
                    return inp.get("name")

            # fallback: input seguinte
            nxt = lab.find_next("input")
            if nxt and nxt.get("name"):
                return nxt.get("name")
    return None

def _extract_rows(html: str) -> List[Dict[str, str]]:
    """
    Extrai as linhas da tabela de rankings na página pesquisável.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []

    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(tds) < 5:
            continue
        if not re.match(r"^\d+$", (tds[0] or "").strip()):
            continue

        rows.append({
            "ranking": tds[0],
            "variacao": tds[1] if len(tds) > 1 else "",
            "licenca": tds[2] if len(tds) > 2 else "",
            "jogador": tds[3] if len(tds) > 3 else "",
            "pontos":  tds[4] if len(tds) > 4 else "",
            "clube":   tds[5] if len(tds) > 5 else "",
            "nivel":   tds[6] if len(tds) > 6 else "",
            "escalao": tds[7] if len(tds) > 7 else "",
            "torneios":tds[8] if len(tds) > 8 else "",
        })

    return rows

def _go_to_search_page(session: requests.Session, gender_block: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Faz:
    1) GET à página top10
    2) POST __doPostBack do 'Ver mais' para ir para a página pesquisável
    Retorna (url_final, html_final, erro)
    """
    r = session.get(SUMMARY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    if _is_searchable_page(r.text):
        return r.url, r.text, None

    target = LOAD_MORE_TARGETS.get(gender_block)
    if not target:
        return None, None, f"Não tenho o EVENTTARGET para '{gender_block}'. (Só está configurado Masculinos.)"

    soup = BeautifulSoup(r.text, "html.parser")
    payload = _collect_form_fields(soup)
    if not payload:
        return None, None, "Não consegui ler o <form> da página top10 (site mudou?)."

    # Simula: javascript:__doPostBack('target','')
    payload["__EVENTTARGET"] = target
    payload["__EVENTARGUMENT"] = ""

    r2 = session.post(SUMMARY_URL, headers={**HEADERS, "Referer": SUMMARY_URL}, data=payload, timeout=30, allow_redirects=True)
    r2.raise_for_status()

    if not _is_searchable_page(r2.text):
        # Mesmo que não detecte pelo texto, pode ter carregado; devolvemos HTML para debug.
        return r2.url, r2.text, "Fiz o postback do 'Ver mais' mas a resposta não parece ser a página pesquisável."

    return r2.url, r2.text, None

def search_weekly_ranking(query: str, gender_block: str = "Masculinos") -> Dict[str, Any]:
    """
    Pesquisa por nome ou licença e devolve ranking/pontos.
    Fluxo:
    - entra na página pesquisável via postback do 'Ver mais'
    - preenche Nome/Licença
    - POST FILTRAR
    - extrai a linha
    """
    q = (query or "").strip()
    if not q:
        return {"found": False, "error": "Pesquisa vazia."}

    s = requests.Session()

    search_url, search_html, err = _go_to_search_page(s, gender_block=gender_block)
    if err:
        # devolve também o url onde ficou, para debug
        return {"found": False, "error": err, "debug_url": search_url}

    soup = BeautifulSoup(search_html, "html.parser")
    payload = _collect_form_fields(soup)
    if not payload:
        return {"found": False, "error": "Na página pesquisável, não consegui ler o <form>."}

    name_field = _find_input_name_by_label(soup, "Nome/Licença") or _find_input_name_by_label(soup, "Nome")
    if not name_field:
        return {"found": False, "error": "Não encontrei o campo 'Nome/Licença' na página pesquisável."}

    payload[name_field] = q

    # Tenta “clicar” no botão FILTRAR (se for submit com name)
    filtrar = soup.find("input", {"type": re.compile("submit", re.I), "value": re.compile(r"filtrar", re.I)})
    if filtrar and filtrar.get("name"):
        payload[filtrar["name"]] = filtrar.get("value", "FILTRAR")

    post_url = search_url or SUMMARY_URL
    r3 = s.post(post_url, headers={**HEADERS, "Referer": post_url}, data=payload, timeout=30)
    r3.raise_for_status()

    rows = _extract_rows(r3.text)
    if not rows:
        return {"found": False, "error": "Após FILTRAR não consegui extrair linhas da tabela (HTML inesperado)."}

    qn = _norm(q)

    # match por licença exacta (quando for número)
    if q.isdigit():
        for row in rows:
            if q == (row.get("licenca") or "").strip():
                return {"found": True, "data": row}

    # match por nome
    for row in rows:
        if qn and qn in _norm(row.get("jogador", "")):
            return {"found": True, "data": row}

    return {"found": False, "error": "Não encontrei o atleta nos resultados."}
