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

def _find_input_by_label(soup: BeautifulSoup, label_text: str) -> str | None:
    """
    Encontra o NAME do <input> associado a um <label> que contenha label_text.
    Funciona com:
      <label for="...">Nome/Licença</label>  <input id="..." name="...">
    e também com layouts em que o input vem logo a seguir.
    """
    # 1) tentar label[for]
    for lab in soup.find_all("label"):
        if label_text.lower() in lab.get_text(" ", strip=True).lower():
            for_attr = lab.get("for")
            if for_attr:
                inp = soup.find(id=for_attr)
                if inp and inp.get("name"):
                    return inp.get("name")

            # 2) fallback: procurar o primeiro input a seguir ao label
            nxt = lab.find_next("input")
            if nxt and nxt.get("name"):
                return nxt.get("name")

    return None


def _find_filter_button_name(soup: BeautifulSoup) -> str | None:
    """
    Descobre o NAME do botão FILTRAR (input submit ou button).
    Precisamos enviar este campo no POST para o servidor aplicar o filtro.
    """
    # input type=submit com value "FILTRAR"
    inp = soup.find("input", {"type": re.compile("submit", re.I), "value": re.compile(r"filtrar", re.I)})
    if inp and inp.get("name"):
        return inp.get("name")

    # button com texto "FILTRAR"
    for btn in soup.find_all("button"):
        if "filtrar" in btn.get_text(" ", strip=True).lower():
            if btn.get("name"):
                return btn.get("name")
            # às vezes button não tem name; nesse caso pode ser postback via __EVENTTARGET,
            # mas muitas páginas ainda aceitam só o submit input.
            break

    return None


@st.cache_data(ttl=300)
def search_player(query: str) -> dict | None:
    s = requests.Session()

    # 1) GET inicial (para VIEWSTATE, EVENTVALIDATION, etc.)
    r = s.get(BASE_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    payload = _collect_form_fields(soup)

    # 2) Encontrar o campo exacto "Nome/Licença"
    name_field = _find_input_by_label(soup, "Nome/Licença")
    if not name_field:
        # fallback: algumas traduções podem ter só "Nome"
        name_field = _find_input_by_label(soup, "Nome")

    if not name_field:
        # debug: ajuda-te a perceber o que existe no form
        st.error("Não consegui localizar o campo 'Nome/Licença' no HTML. O site pode ter mudado.")
        with st.expander("Debug (nomes de inputs no form)"):
            st.write(sorted(list(payload.keys()))[:200])
        return None

    payload[name_field] = query.strip()

    # 3) Simular clique no botão FILTRAR
    filtrar_name = _find_filter_button_name(soup)
    if filtrar_name:
        payload[filtrar_name] = "FILTRAR"
    else:
        # fallback: às vezes o botão é um input sem name mas com id
        # e a app aceita só o payload com o campo preenchido; tentamos na mesma.
        pass

    # 4) POST
    r2 = s.post(BASE_URL, headers=HEADERS, data=payload, timeout=25)
    r2.raise_for_status()

    rows = _extract_rows(r2.text)

    if not rows:
        # debug: mostra um excerto do html para veres se ele devolveu outra coisa
        with st.expander("Debug: sem linhas extraídas (primeiros 800 chars)"):
            st.code(r2.text[:800])
        return None

    # 5) Escolher o melhor match
    qlow = query.strip().lower()
    for row in rows:
        if qlow in (row["jogador"] or "").lower() or query.strip() == (row["licenca"] or "").strip():
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
