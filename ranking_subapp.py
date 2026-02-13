import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

BASE = "https://tour.tiesports.com/fpp/weekly_rankings"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://tour.tiesports.com",
    "x-microsoftajax": "Delta=true",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
}


def _get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # Campos WebForms típicos
    for k in [
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
        "__SCROLLPOSITIONX",
        "__SCROLLPOSITIONY",
    ]:
        el = soup.find("input", {"id": k}) or soup.find("input", {"name": k})
        if el and el.get("value") is not None:
            data[k] = el["value"]

    # HiddenField_*
    for inp in soup.select("input[type='hidden']"):
        name = inp.get("name")
        if name and name.startswith("HiddenField_") and inp.get("value") is not None:
            data[name] = inp["value"]

    return data


def _extract_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    rows = []
    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.select("td")]
        # Esperado: Ranking | Licença | Jogador | Pontos | Escalão | (botão)
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


def _normalize_points(pt_str: str) -> float | None:
    # Ex: "169.375,00" -> 169375.00
    s = (pt_str or "").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


@st.cache_data(ttl=300)
def fetch_player_by_license(license_no: str, rank: str, gender: str, group: str, date_str: str | None) -> dict | None:
    """
    Faz GET + vários POST ("Ver mais") até encontrar a licença.
    Sem cookies hardcoded. Session gere cookies automaticamente.
    """

    params = {"rank": rank}
    url = f"{BASE}?rank={rank}"

    s = requests.Session()

    # GET inicial
    r = s.get(url, params=params, timeout=25)
    r.raise_for_status()
    html = r.text

    # tenta logo
    for row in _extract_rows(html):
        if row["licenca"] == str(license_no):
            return row

    # Vamos tentar carregar mais blocos
    # Em alguns sites o ctl00 pode variar; começamos pelo ctl00 como no teu cURL
    # e, se necessário, tentamos ctl00..ctl20.
    event_targets = [f"repeater_rankings_top_10$ctl{str(i).zfill(2)}$link_load_more_men" for i in range(0, 21)]

    # Se género for Women, o link pode ser diferente (fallback)
    if gender.lower().startswith("w"):
        event_targets = [t.replace("_men", "_women") for t in event_targets]

    for ev in event_targets:
        hidden = _get_hidden_fields(html)

        payload = {
            "ScriptManager1": f"UpdatePanel5|{ev}",
            "__EVENTTARGET": ev,
            "__EVENTARGUMENT": "",
            "__ASYNCPOST": "true",

            # o rank vem no query string, mas metemos também no body para consistência
            "rank": rank,
        }
        payload.update(hidden)

        # Alguns formulários têm estes campos; se existirem no HTML, já entram via hidden.
        # Se quiseres forçar filtros (género/grupo/data), teríamos de saber os "name" exactos
        # dos inputs do formulário — podemos adicionar depois com base no HTML real.

        r2 = s.post(url, headers={**HEADERS, "referer": url}, data=payload, timeout=25)
        r2.raise_for_status()
        html = r2.text

        for row in _extract_rows(html):
            if row["licenca"] == str(license_no):
                return row

    return None


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nº de licença e mostra a posição/pontos no ranking.")

    col1, col2, col3, col4 = st.columns([1.2, 1, 1, 1])

    with col1:
        lic = st.text_input("Nº licença", value="", placeholder="ex: 17017")

    with col2:
        gender = st.selectbox("Género", ["Men", "Women"], index=0)

    with col3:
        group = st.selectbox("Grupo etário", ["Absolutos"], index=0)

    with col4:
        rank = st.selectbox("Ranking", ["absolutos"], index=0)

    # (Opcional) data. Se quiseres ligar ao dropdown do site, diz-me e eu ajusto.
    date_str = None

    btn = st.button("🔎 Procurar", use_container_width=True, disabled=(not lic.strip()))

    if btn:
        with st.spinner("A consultar ranking…"):
            res = fetch_player_by_license(
                license_no=lic.strip(),
                rank=rank,
                gender=gender,
                group=group,
                date_str=date_str,
            )

        if not res:
            st.warning("Não encontrei essa licença nos resultados carregados. Pode estar muito abaixo no ranking ou o site mudou o evento 'Ver mais'.")
            st.info("Se me disseres em que página aparece (ex.: 7/8/9), eu ajusto para carregar mais blocos/paginação.")
            return

        pts_float = _normalize_points(res["pontos"])
        st.success("Encontrado ✅")

        a, b, c = st.columns(3)
        a.metric("Ranking", res["ranking"])
        b.metric("Licença", res["licenca"])
        c.metric("Pontos", f"{pts_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if pts_float is not None else res["pontos"])

        st.markdown("### Detalhe")
        st.write(
            {
                "Jogador": res["jogador"],
                "Escalão": res.get("escalao", ""),
                "Pontos (texto)": res["pontos"],
            }
        )

        st.link_button("Abrir no site", f"{BASE}?rank={rank}")
