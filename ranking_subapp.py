import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

BASE_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

HEADERS_ASYNC = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://tour.tiesports.com",
    "referer": BASE_URL,
    "x-microsoftajax": "Delta=true",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
}

UPDATE_PANEL_ID = "UpdatePanel5"


def _extract_updatepanel_html(delta_text: str, panel_id: str = UPDATE_PANEL_ID) -> str:
    if "|updatePanel|" not in delta_text:
        return delta_text
    parts = delta_text.split("|")
    for i in range(len(parts) - 2):
        if parts[i] == "updatePanel" and parts[i + 1] == panel_id:
            return parts[i + 2] or ""
    return ""


def _get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {}
    for inp in soup.select("input[type='hidden']"):
        name = inp.get("name")
        if name:
            data[name] = inp.get("value", "")
    return data


def _extract_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(strip=True) for td in tr.select("td")]
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


def _find_pager_link_eventtargets(html: str) -> dict[int, str]:
    """
    Encontra os links do pager e mapeia página -> __EVENTTARGET.
    Em WebForms geralmente vem no href: javascript:__doPostBack('EVENTTARGET','')
    """
    soup = BeautifulSoup(html, "html.parser")
    mapping = {}

    # procurar qualquer <a href="javascript:__doPostBack('X','')">n</a>
    for a in soup.select("a[href*='__doPostBack']"):
        txt = a.get_text(strip=True)
        if not txt.isdigit():
            continue
        page_num = int(txt)

        href = a.get("href", "")
        m = re.search(r"__doPostBack\('([^']+)','([^']*)'\)", href)
        if m:
            eventtarget = m.group(1)
            mapping[page_num] = eventtarget

    return mapping


def _postback(session: requests.Session, html: str, eventtarget: str, eventargument: str = "") -> str:
    """
    Faz um postback AJAX para o UpdatePanel.
    Retorna o HTML do UpdatePanel.
    """
    hidden = _get_hidden_fields(html)

    payload = dict(hidden)
    payload["__EVENTTARGET"] = eventtarget
    payload["__EVENTARGUMENT"] = eventargument
    payload["__ASYNCPOST"] = "true"

    # ScriptManager1 costuma existir e é usado nos async postbacks
    # Se existir, usamos o mesmo UpdatePanel5|<eventtarget>
    payload["ScriptManager1"] = f"{UPDATE_PANEL_ID}|{eventtarget}"

    r = session.post(BASE_URL, headers=HEADERS_ASYNC, data=payload, timeout=25)
    r.raise_for_status()

    panel_html = _extract_updatepanel_html(r.text, panel_id=UPDATE_PANEL_ID)
    # o panel_html é um fragmento; guardamos o HTML inteiro para próximos hidden fields:
    # mas os hidden fields actualizados vêm no delta também.
    # Para simplificar: devolvemos o texto inteiro (delta) para manter hidden fields acessíveis.
    return r.text


@st.cache_data(ttl=300)
def fetch_license_at_page(license_no: str, target_page: int = 64) -> dict | None:
    """
    Vai até à página target_page usando o pager __doPostBack e procura a licença nessa página.
    """
    s = requests.Session()

    # 1) GET inicial
    r0 = s.get(BASE_URL, timeout=25)
    r0.raise_for_status()
    html_full = r0.text

    # tenta logo na página 1
    for row in _extract_rows(html_full):
        if row["licenca"] == str(license_no):
            row["page"] = 1
            return row

    # 2) descobrir eventtargets do pager na página actual
    pager_map = _find_pager_link_eventtargets(html_full)

    # Se a página target não estiver visível no pager actual (normal), temos de ir avançando.
    # Estratégia:
    # - enquanto target não estiver disponível, clicamos no "..." (se existir) ou no maior número disponível
    # - depois clicamos no target
    current_html_full = html_full

    for _ in range(120):  # limite de segurança
        pager_map = _find_pager_link_eventtargets(current_html_full)

        if target_page in pager_map:
            # clicar directamente na página target
            delta = _postback(s, current_html_full, pager_map[target_page], "")
            # após postback, o delta contém novos hiddenfields; mas o UpdatePanel tem a tabela
            panel_html = _extract_updatepanel_html(delta, UPDATE_PANEL_ID)
            for row in _extract_rows(panel_html):
                if row["licenca"] == str(license_no):
                    row["page"] = target_page
                    return row
            return None

        # não aparece: precisamos “saltar” para a frente
        # escolhe a maior página que aparece no pager e clica nela (empurra a janela)
        if pager_map:
            max_visible = max(pager_map.keys())
            delta = _postback(s, current_html_full, pager_map[max_visible], "")
            current_html_full = delta  # delta para continuar a ter hidden fields
            continue

        # se não encontrou pager_map, aborta
        return None

    return None


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nº de licença e mostra a posição/pontos no ranking.")

    col1, col2 = st.columns([1.2, 1])
    with col1:
        lic = st.text_input("Nº licença", value="17017", placeholder="ex: 17017")
    with col2:
        page = st.number_input("Página (do site)", min_value=1, max_value=200, value=64, step=1)

    if st.button("🔎 Procurar", use_container_width=True, disabled=not lic.strip()):
        with st.spinner(f"A consultar ranking (a saltar para a página {page})…"):
            res = fetch_license_at_page(lic.strip(), int(page))

        if not res:
            st.warning("Não encontrei nessa página (ou o pager mudou).")
            st.info("Se me deres o 'Copy as cURL' do clique na página 2 do pager, eu deixo isto 100% exacto.")
            return

        st.success("Encontrado ✅")
        a, b, c, d = st.columns(4)
        a.metric("Página", str(res.get("page", "")))
        b.metric("Ranking", res["ranking"])
        c.metric("Licença", res["licenca"])
        d.metric("Pontos", res["pontos"])
        st.write({"Jogador": res["jogador"], "Escalão": res.get("escalao", "")})
        st.link_button("Abrir no site", BASE_URL)
