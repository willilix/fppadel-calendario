import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

BASE_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

PAGER_EVENTTARGET = "DataPager_ranking_players$ctl00$ctl04"

HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
    "referer": BASE_URL,
    "origin": "https://tour.tiesports.com",
}

def _extract_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.select("td")]
        # Esperado: Ranking | Licença | Jogador | Pontos | Escalão | ...
        if len(tds) >= 4 and tds[0].isdigit():
            rows.append(
                {
                    "ranking": tds[0],
                    "licenca": tds[1],
                    "jogador": tds[2],
                    "pontos": tds[3],
                    "escalao": tds[4] if len(tds) >= 5 else "",
                }
            )
    return rows

def _collect_form_fields(soup: BeautifulSoup) -> dict:
    """
    Recolhe TODOS os campos do <form> como o browser faria:
    - inputs (inclui hidden)
    - selects (opção seleccionada)
    - textareas
    """
    form = soup.find("form")
    if not form:
        return {}

    data = {}

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
        opt = sel.find("option", selected=True)
        if not opt:
            opt = sel.find("option")
        data[name] = opt.get("value", "") if opt else ""

    # textareas
    for ta in form.select("textarea"):
        name = ta.get("name")
        if not name:
            continue
        data[name] = ta.text or ""

    return data

def _looks_like_page(html: str, page: int) -> bool:
    """
    Heurística para validar se estamos na página certa:
    - o pager costuma ter a página actual com uma classe/estilo diferente
    - e/ou existe um botão/elemento com o número da página em destaque
    """
    # muito simples e permissivo:
    return bool(re.search(rf">\s*{page}\s*<", html))

@st.cache_data(ttl=300)
def fetch_player_by_license(license_no: str, page: int = 64) -> dict | None:
    s = requests.Session()

    # 1) GET inicial (para VIEWSTATE, EVENTVALIDATION, etc.)
    r = s.get(BASE_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    base_payload = _collect_form_fields(soup)

    # 2) se já estiver na página 1 e por acaso contém a licença
    for row in _extract_rows(r.text):
        if row["licenca"] == str(license_no):
            row["page"] = 1
            return row

    # 3) tentar saltar para a página desejada com diferentes __EVENTARGUMENT
    # (porque não temos o valor exacto do argumento capturado)
    candidates = [
        str(page),
        str(page - 1),                # 0-based comum
        f"Page${page}",
        f"Page${page-1}",
        f"{page}$",                   # alguns DataPagers usam sufixos
        f"{page-1}$",
        "",                           # alguns casos (raro)
    ]

    for arg in candidates:
        payload = dict(base_payload)
        payload["__EVENTTARGET"] = PAGER_EVENTTARGET
        payload["__EVENTARGUMENT"] = arg

        r2 = s.post(BASE_URL, headers=HEADERS, data=payload, timeout=25)
        r2.raise_for_status()

        html2 = r2.text

        # validar rapidamente que mudámos de página (best effort)
        # mesmo que a heurística falhe, ainda tentamos extrair
        rows = _extract_rows(html2)
        if rows:
            for row in rows:
                if row["licenca"] == str(license_no):
                    row["page"] = page
                    row["eventargument_used"] = arg
                    return row

        # Se não encontrou, continuar a tentar próximos argumentos

    return None


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nº de licença e mostra a posição/pontos no ranking.")

    col1, col2 = st.columns([1.2, 1])
    with col1:
        lic = st.text_input("Nº licença", value="17017", placeholder="ex: 17017")
    with col2:
        page = st.number_input("Página (do site)", min_value=1, max_value=500, value=64, step=1)

    if st.button("🔎 Procurar", use_container_width=True, disabled=not lic.strip()):
        with st.spinner(f"A consultar ranking (página {int(page)})…"):
            res = fetch_player_by_license(lic.strip(), page=int(page))

        if not res:
            st.warning("Não encontrei essa licença nessa página (ou o site mudou o padrão do pager).")
            st.info("Se quiseres, eu faço o ajuste final se me deres o valor do __EVENTARGUMENT quando clicas na página 64.")
            return

        st.success("Encontrado ✅")
        a, b, c, d = st.columns(4)
        a.metric("Página", str(res.get("page", "")))
        b.metric("Ranking", res["ranking"])
        c.metric("Licença", res["licenca"])
        d.metric("Pontos", res["pontos"])
        st.write({"Jogador": res["jogador"], "Escalão": res.get("escalao", "")})

        # opcional: debug
        st.caption(f"EVENTARGUMENT usado: {res.get('eventargument_used', '')}")
        st.link_button("Abrir no site", BASE_URL)
