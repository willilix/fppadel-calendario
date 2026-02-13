import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

BASE_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

HEADERS = {
    "user-agent": "Mozilla/5.0",
    "referer": BASE_URL,
    "origin": "https://tour.tiesports.com",
}


def _collect_form_fields(soup: BeautifulSoup) -> dict:
    form = soup.find("form")
    if not form:
        return {}

    data = {}

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
        opt = sel.find("option", selected=True)
        if not opt:
            opt = sel.find("option")
        data[name] = opt.get("value", "") if opt else ""

    return data


def _extract_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.select("td")]

        # layout da página completa:
        # Ranking | Variação | Licença | Jogador | Pontos | ...
        if len(tds) >= 5 and tds[0].isdigit():
            rows.append(
                {
                    "ranking": tds[0],
                    "licenca": tds[2],
                    "jogador": tds[3],
                    "pontos": tds[4],
                    "clube": tds[5] if len(tds) > 5 else "",
                    "nivel": tds[6] if len(tds) > 6 else "",
                    "escalao": tds[7] if len(tds) > 7 else "",
                    "torneios": tds[8] if len(tds) > 8 else "",
                }
            )
    return rows


@st.cache_data(ttl=300)
def search_player(query: str):
    s = requests.Session()

    # 1) GET inicial para obter VIEWSTATE
    r = s.get(BASE_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    payload = _collect_form_fields(soup)

    # 2) descobrir qual é o campo do Nome/Licença automaticamente
    name_field = None
    for k in payload.keys():
        if "nome" in k.lower() or "license" in k.lower() or "licenca" in k.lower():
            name_field = k
            break

    if not name_field:
        return None

    payload[name_field] = query

    # 3) submeter formulário
    r2 = s.post(BASE_URL, headers=HEADERS, data=payload, timeout=25)
    r2.raise_for_status()

    rows = _extract_rows(r2.text)

    if not rows:
        return None

    # devolver primeira correspondência
    for row in rows:
        if query.lower() in row["jogador"].lower() or query == row["licenca"]:
            return row

    return rows[0]


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nome ou nº de licença e mostra posição/pontos.")

    query = st.text_input("Nome ou nº licença", placeholder="Ex: Lucas Francisco ou 17017")

    if st.button("🔎 Procurar", use_container_width=True, disabled=not query.strip()):
        with st.spinner("A consultar ranking…"):
            res = search_player(query.strip())

        if not res:
            st.warning("Não encontrei esse atleta.")
            return

        st.success("Encontrado ✅")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ranking", res["ranking"])
        c2.metric("Licença", res["licenca"])
        c3.metric("Pontos", res["pontos"])
        c4.metric("Escalão", res["escalao"])

        st.write({
            "Jogador": res["jogador"],
            "Clube": res["clube"],
            "Nível": res["nivel"],
            "Torneios": res["torneios"],
        })

        st.link_button("Abrir no site", BASE_URL)
