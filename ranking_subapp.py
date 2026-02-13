import requests
import streamlit as st
from bs4 import BeautifulSoup

BASE_URL = "https://tour.tiesports.com/fpp/weekly_rankings"

HEADERS_ASYNC = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://tour.tiesports.com",
    "x-microsoftajax": "Delta=true",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
}


def _extract_updatepanel_html(delta_text: str, panel_id: str = "UpdatePanel5") -> str:
    """
    ASP.NET UpdatePanel async response vem tipo:
    ...|updatePanel|UpdatePanel5|<html_fragment>|hiddenField|__VIEWSTATE|...
    """
    if "|updatePanel|" not in delta_text:
        return delta_text  # já é HTML normal (fallback)

    parts = delta_text.split("|")
    for i in range(len(parts) - 2):
        if parts[i] == "updatePanel" and parts[i + 1] == panel_id:
            return parts[i + 2] or ""
    return ""


def _get_hidden_fields_from_soup(soup: BeautifulSoup) -> dict:
    data = {}
    for inp in soup.select("input[type='hidden']"):
        name = inp.get("name")
        if not name:
            continue
        data[name] = inp.get("value", "")
    return data


def _extract_rows_from_html(html: str) -> list[dict]:
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


def _find_input_name_for_license(soup: BeautifulSoup) -> str | None:
    """
    Encontra o input do filtro "Nome/Licença" (normalmente é um <input> text).
    Tentamos por placeholder/label e fallback por 1º text input dentro do bloco de filtros.
    """
    # 1) por placeholder (o site mostra "Nome/Licença")
    inp = soup.find("input", attrs={"placeholder": lambda v: v and "Lic" in v})
    if inp and inp.get("name"):
        return inp["name"]

    # 2) por label próximo (simplificado)
    # tenta encontrar o texto "Nome/Licença" e depois o próximo input
    label = soup.find(string=lambda s: s and "Nome/Lic" in s)
    if label:
        parent = label.parent
        if parent:
            nxt = parent.find_next("input")
            if nxt and nxt.get("name"):
                return nxt["name"]

    # 3) fallback: primeiro input text visível
    for i in soup.select("input"):
        t = (i.get("type") or "").lower()
        if t in ("text", "") and i.get("name"):
            return i["name"]

    return None


def _find_filter_button_name_value(soup: BeautifulSoup) -> tuple[str, str] | None:
    """
    Encontra o botão "FILTRAR" (name e value).
    """
    # input type=submit/button com value 'FILTRAR'
    btn = soup.find("input", attrs={"value": lambda v: v and v.strip().lower() == "filtrar"})
    if btn and btn.get("name"):
        return btn["name"], btn.get("value", "FILTRAR")

    # button tag com texto 'FILTRAR'
    b = soup.find("button", string=lambda s: s and s.strip().lower() == "filtrar")
    if b and b.get("name"):
        return b["name"], b.get_text(strip=True) or "FILTRAR"

    return None


@st.cache_data(ttl=300)
def fetch_player_by_license(license_no: str, rank: str = "absolutos") -> dict | None:
    """
    Estratégia:
    1) GET a página
    2) POST 'FILTRAR' com Nome/Licença = license_no (como o UI)
    3) Parse UpdatePanel5 e procurar a linha
    """
    url = f"{BASE_URL}?rank={rank}"
    s = requests.Session()

    # 1) GET
    r = s.get(url, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    hidden = _get_hidden_fields_from_soup(soup)
    license_field_name = _find_input_name_for_license(soup)
    btn = _find_filter_button_name_value(soup)

    if not license_field_name or not btn:
        # fallback: tentar extrair no HTML inicial (top10)
        for row in _extract_rows_from_html(r.text):
            if row["licenca"] == str(license_no):
                return row
        return None

    btn_name, btn_value = btn

    # 2) POST como async UpdatePanel
    payload = dict(hidden)

    # campo Nome/Licença
    payload[license_field_name] = str(license_no)

    # "clicar" no botão filtrar: em WebForms normalmente inclui-se o name do botão
    payload[btn_name] = btn_value

    # ScriptManager1 existe e é usado como no teu cURL (se existir no hidden já vem)
    # mas garantimos o padrão UpdatePanel5|<eventtarget>
    payload["ScriptManager1"] = f"UpdatePanel5|{btn_name}"
    payload["__EVENTTARGET"] = btn_name
    payload["__EVENTARGUMENT"] = ""
    payload["__ASYNCPOST"] = "true"

    r2 = s.post(url, headers={**HEADERS_ASYNC, "referer": url}, data=payload, timeout=25)
    r2.raise_for_status()

    panel_html = _extract_updatepanel_html(r2.text, panel_id="UpdatePanel5")
    rows = _extract_rows_from_html(panel_html)

    for row in rows:
        if row["licenca"] == str(license_no):
            return row

    return None


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nº de licença e mostra a posição/pontos no ranking.")

    col1, col2 = st.columns([1.2, 1])
    with col1:
        lic = st.text_input("Nº licença", value="", placeholder="ex: 17017")
    with col2:
        rank = st.selectbox("Ranking", ["absolutos"], index=0)

    if st.button("🔎 Procurar", use_container_width=True, disabled=not lic.strip()):
        with st.spinner("A consultar ranking…"):
            res = fetch_player_by_license(lic.strip(), rank=rank)

        if not res:
            st.warning("Não encontrei essa licença com o filtro. (Pode ser mudança no HTML do site.)")
            st.info("Se quiseres, eu afino o parser com um 'Copy as cURL' do botão FILTRAR (sem cookies).")
            return

        st.success("Encontrado ✅")
        a, b, c = st.columns(3)
        a.metric("Ranking", res["ranking"])
        b.metric("Licença", res["licenca"])
        c.metric("Pontos", res["pontos"])

        st.write({"Jogador": res["jogador"], "Escalão": res.get("escalao", "")})
        st.link_button("Abrir no site", f"{BASE_URL}?rank={rank}")
