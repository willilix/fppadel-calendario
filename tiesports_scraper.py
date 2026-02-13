import re
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from unidecode import unidecode


SUMMARY_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Origin": "https://tour.tiesports.com",
    "Referer": SUMMARY_URL,
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode((s or "").strip().lower()))


def _collect_form_fields(soup: BeautifulSoup) -> Dict[str, str]:
    form = soup.find("form")
    if not form:
        return {}

    data: Dict[str, str] = {}

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

    for sel in form.select("select"):
        name = sel.get("name")
        if not name:
            continue
        opt = sel.find("option", selected=True) or sel.find("option")
        data[name] = opt.get("value", "") if opt else ""

    for ta in form.select("textarea"):
        name = ta.get("name")
        if name:
            data[name] = ta.text or ""

    return data


def _find_by_label_input_name(soup: BeautifulSoup, label_contains: str) -> Optional[str]:
    for lab in soup.find_all("label"):
        txt = lab.get_text(" ", strip=True).lower()
        if label_contains.lower() in txt:
            for_attr = lab.get("for")
            if for_attr:
                inp = soup.find(id=for_attr)
                if inp and inp.get("name"):
                    return inp.get("name")
            nxt = lab.find_next("input")
            if nxt and nxt.get("name"):
                return nxt.get("name")
    return None


def _parse_do_postback(href: str) -> Optional[Tuple[str, str]]:
    """
    Parse: javascript:__doPostBack('TARGET','ARG')
    """
    if not href:
        return None
    m = re.search(r"__doPostBack\('([^']*)','([^']*)'\)", href)
    if m:
        return m.group(1), m.group(2)
    return None


def _is_searchable_page(html: str) -> bool:
    # heurística: a página pesquisável tem label "Nome/Licença" e botão "FILTRAR"
    h = html.lower()
    return ("nome/licença" in h or "nome/licenca" in h) and ("filtrar" in h)


def _find_ver_mais_action(soup: BeautifulSoup, gender_block: str = "Masculinos") -> Dict[str, Any]:
    """
    Tenta encontrar a acção do botão 'Ver mais' do bloco Masculinos/Femininos/Mistos.
    Devolve:
      {"kind": "href", "url": "..."}  OU
      {"kind": "postback", "target": "...", "argument": "..."}  OU
      {"kind": "unknown"}
    """
    # 1) encontrar header do bloco: "Masculinos [ ... ]"
    header = soup.find(string=re.compile(rf"{re.escape(gender_block)}\s*\[", re.I))
    if not header:
        return {"kind": "unknown"}

    # 2) procurar o primeiro elemento "Ver mais" depois desse header
    # Tentamos <a> e <button>
    header_node = header.parent if hasattr(header, "parent") else None
    start = header_node or soup

    # procura a seguir no DOM por links/botões "Ver mais"
    ver_mais_a = start.find_next("a", string=re.compile(r"^\s*Ver mais\s*$", re.I))
    if ver_mais_a:
        href = ver_mais_a.get("href", "")
        if href and not href.lower().startswith("javascript:"):
            return {"kind": "href", "url": urljoin(SUMMARY_URL, href)}
        pb = _parse_do_postback(href)
        if pb:
            return {"kind": "postback", "target": pb[0], "argument": pb[1]}

    ver_mais_btn = start.find_next("button", string=re.compile(r"^\s*Ver mais\s*$", re.I))
    if ver_mais_btn:
        # pode ter onclick com __doPostBack
        onclick = ver_mais_btn.get("onclick", "")
        pb = _parse_do_postback(onclick)
        if pb:
            return {"kind": "postback", "target": pb[0], "argument": pb[1]}

    return {"kind": "unknown"}


def _extract_rows(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []

    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(tds) < 5:
            continue
        if not re.match(r"^\d+$", (tds[0] or "").strip()):
            continue

        row = {
            "ranking": tds[0],
            "variacao": tds[1] if len(tds) > 1 else "",
            "licenca": tds[2] if len(tds) > 2 else "",
            "jogador": tds[3] if len(tds) > 3 else "",
            "pontos":  tds[4] if len(tds) > 4 else "",
            "clube":   tds[5] if len(tds) > 5 else "",
            "nivel":   tds[6] if len(tds) > 6 else "",
            "escalao": tds[7] if len(tds) > 7 else "",
            "torneios":tds[8] if len(tds) > 8 else "",
        }
        rows.append(row)

    return rows


def _go_to_search_page(session: requests.Session, gender_block: str = "Masculinos") -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    1) GET à página resumo (top10)
    2) Descobre como funciona o 'Ver mais'
    3) Executa a navegação/POSTBACK
    Retorna: (final_url, html, error)
    """
    r = session.get(SUMMARY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    if _is_searchable_page(r.text):
        return r.url, r.text, None

    soup = BeautifulSoup(r.text, "html.parser")
    action = _find_ver_mais_action(soup, gender_block=gender_block)

    if action["kind"] == "href":
        url = action["url"]
        r2 = session.get(url, headers={**HEADERS, "Referer": SUMMARY_URL}, timeout=30)
        r2.raise_for_status()
        if _is_searchable_page(r2.text):
            return r2.url, r2.text, None
        return r2.url, r2.text, "Cheguei a uma página, mas ainda não vejo filtros (Nome/Licença + FILTRAR)."

    if action["kind"] == "postback":
        payload = _collect_form_fields(soup)
        if not payload:
            return None, None, "Não consegui ler o <form> da página resumo para simular o postback."

        payload["__EVENTTARGET"] = action["target"]
        payload["__EVENTARGUMENT"] = action["argument"]

        r2 = session.post(SUMMARY_URL, headers={**HEADERS, "Referer": SUMMARY_URL}, data=payload, timeout=30, allow_redirects=True)
        r2.raise_for_status()

        if _is_searchable_page(r2.text):
            return r2.url, r2.text, None

        return r2.url, r2.text, "Postback feito, mas a resposta ainda não parece ser a página pesquisável."

    return None, None, "Não consegui encontrar automaticamente o botão 'Ver mais' (ou mudou o HTML)."


def search_weekly_ranking(query: str, gender_block: str = "Masculinos") -> Dict[str, Any]:
    """
    Versão final:
    - entra na página pesquisável via 'Ver mais' (href ou postback)
    - submete o filtro com Nome/Licença
    - extrai a linha do atleta (nome ou licença)
    """
    q = (query or "").strip()
    if not q:
        return {"found": False, "error": "Pesquisa vazia."}

    s = requests.Session()

    search_url, search_html, err = _go_to_search_page(s, gender_block=gender_block)
    if err:
        return {"found": False, "error": f"Não consegui chegar à página pesquisável: {err}"}

    # agora estamos na página pesquisável
    soup = BeautifulSoup(search_html, "html.parser")
    payload = _collect_form_fields(soup)
    if not payload:
        return {"found": False, "error": "Na página pesquisável, não consegui ler o <form>."}

    name_field = _find_by_label_input_name(soup, "Nome/Licença") or _find_by_label_input_name(soup, "Nome")
    if not name_field:
        return {"found": False, "error": "Não encontrei o campo 'Nome/Licença' na página pesquisável."}

    payload[name_field] = q

    # tentar identificar um submit do botão FILTRAR (se existir como input)
    # se não houver, muitas vezes basta o campo preenchido + POST com viewstate
    filtrar_input = soup.find("input", {"type": re.compile("submit", re.I), "value": re.compile(r"filtrar", re.I)})
    if filtrar_input and filtrar_input.get("name"):
        payload[filtrar_input["name"]] = filtrar_input.get("value", "FILTRAR")

    # POST para a página pesquisável (normalmente o action é o próprio URL)
    post_url = search_url or SUMMARY_URL
    r2 = s.post(post_url, headers={**HEADERS, "Referer": post_url}, data=payload, timeout=30)
    r2.raise_for_status()

    rows = _extract_rows(r2.text)
    if not rows:
        return {"found": False, "error": "Fiz FILTRAR mas não consegui extrair linhas da tabela (HTML inesperado)."}

    qn = _norm(q)
    for row in rows:
        if q.isdigit() and q == (row.get("licenca") or "").strip():
            return {"found": True, "data": row}
        if qn and qn in _norm(row.get("jogador", "")):
            return {"found": True, "data": row}

    return {"found": False, "error": "Não encontrei o atleta nos resultados."}
