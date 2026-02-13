import os
import re
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote_plus

import pandas as pd
import pdfplumber
import requests
import streamlit as st
from bs4 import BeautifulSoup

HOME_URL = "https://fppadel.pt/"
WP_MEDIA_SEARCH = "https://fppadel.pt/wp-json/wp/v2/media"

MONTHS = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"
]

st.set_page_config(page_title="Calendário FPPadel", layout="wide")


def _pick_highest_version(urls: list[str]) -> str:
    def score(u: str) -> int:
        m = re.search(r"-(\d+)\.pdf$", u)
        return int(m.group(1)) if m else -1

    urls = list(set(urls))
    urls.sort(key=lambda u: (score(u), u), reverse=True)
    return urls[0]


@st.cache_data(ttl=900)  # 15 min
def find_latest_calendar_pdf_url() -> str:
    # 1) tenta encontrar na home
    try:
        html = requests.get(HOME_URL, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = (a.get_text() or "").strip().lower()

            if "saber mais" in text and href.lower().endswith(".pdf") and "calend" in href.lower():
                candidates.append(urljoin(HOME_URL, href))

        if candidates:
            return _pick_highest_version(candidates)
    except Exception:
        pass

    # 2) fallback: WP REST API
    found = []
    for term in ["CALENDARIO-ACTIVIDADES-PROVISORIO", "RG-01-CALENDARIO-ACTIVIDADES"]:
        try:
            r = requests.get(WP_MEDIA_SEARCH, params={"search": term, "per_page": 100}, timeout=20)
            if r.status_code != 200:
                continue
            items = r.json()
            for it in items:
                src = (it.get("source_url") or "").strip()
                if src.lower().endswith(".pdf") and "calend" in src.lower():
                    found.append(src)
        except Exception:
            continue

    if not found:
        raise RuntimeError("Não consegui encontrar o PDF do calendário (nem na home, nem via WP media).")

    return _pick_highest_version(found)


@st.cache_data(ttl=900)
def download_pdf_bytes(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, timeout=30)
    r.raise_for_status()
    return r.content


def parse_calendar_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Parser robusto para PDFs onde as "colunas" vêm separadas por 1 espaço (não por múltiplos).
    Extrai: Data (mês+dia), DIV (ABS/JOV), Actividade, Categorias, Classe, Local, Organização.
    """

    def looks_like_money(tok: str) -> bool:
        # Ex: 2.000 10.000 50.000 25.000
        return bool(re.fullmatch(r"[´']?\d{1,3}(?:\.\d{3})*(?:,\d+)?", tok))

    def is_category_token(tok: str) -> bool:
        # Tokens típicos de categoria: F1, M3, S14, etc.
        return bool(re.fullmatch(r"(F|M|S)\d{1,2}", tok)) or tok in {"VET", "FIP"}

    rows = []
    current_month = None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                upper = line.upper()

                # ignora cabeçalhos
                if "MÊS" in upper and "ACTIVIDADES" in upper and "DIV" in upper:
                    continue
                if upper.startswith("CALEND"):
                    continue

                # detectar mês (muitas vezes vem como "FEVEREIRO 4 a 8 CIR ABS ...")
                month_found = None
                for m in MONTHS:
                    if upper.startswith(m + " "):
                        month_found = m
                        break
                if month_found:
                    current_month = month_found
                    line = line[len(month_found):].strip()
                elif upper in MONTHS:
                    current_month = upper
                    continue

                if not current_month:
                    continue

                tokens = line.split()

                # encontrar DIV
                div_idx = None
                for i, t in enumerate(tokens):
                    if t in ("ABS", "JOV"):
                        div_idx = i
                        break
                if div_idx is None:
                    continue

                div = tokens[div_idx]

                # antes do DIV: data + tipo (tipo pode ser 1-2 tokens)
                pre = tokens[:div_idx]
                tipo_set = {"CIR", "FPP", "FOR", "INT"}

                if len(pre) >= 2 and pre[-2] in tipo_set:
                    date = " ".join(pre[:-2]).strip()
                elif len(pre) >= 1 and pre[-1] in tipo_set:
                    date = " ".join(pre[:-1]).strip()
                else:
                    date = " ".join(pre).strip()

                rest = tokens[div_idx + 1:]
                if not rest:
                    continue

                # localizar token com € (prize-money). No PDF, normalmente:
                # ... CLASSE  PRIZE€  LOCAL  ORGANIZAÇÃO...
                euro_idx = None
                for i, t in enumerate(rest):
                    if "€" in t:
                        euro_idx = i
                        break

                local = ""
                organizacao = ""

                if euro_idx is not None and euro_idx + 1 < len(rest):
                    local = rest[euro_idx + 1]
                    if euro_idx + 2 < len(rest):
                        organizacao = " ".join(rest[euro_idx + 2:]).strip()
                else:
                    # fallback se não apanharmos o € (raro)
                    local = rest[-1]
                    organizacao = ""

                # determinar classe
                class_end = euro_idx if euro_idx is not None else len(rest)
                classe = ""
                class_start = None

                # caso "A definir"
                for i in range(max(0, class_end - 3), class_end):
                    if i + 1 < class_end and rest[i].lower() == "a" and rest[i + 1].lower().startswith("definir"):
                        classe = "A definir"
                        class_start = i
                        break

                if not classe:
                    for i in range(class_end - 1, -1, -1):
                        if looks_like_money(rest[i]):
                            class_start = i
                            if i + 2 < class_end and rest[i + 1] == "/" and rest[i + 2][0].isalpha():
                                classe = " ".join(rest[i:i + 3])
                            elif i + 1 < class_end and "/" in rest[i + 1]:
                                classe = " ".join(rest[i:i + 2])
                            else:
                                classe = rest[i]
                            break

                if class_start is None:
                    class_start = class_end

                # categorias
                cat_start = None
                for i, t in enumerate(rest):
                    if i >= class_start:
                        break
                    if is_category_token(t):
                        cat_start = i
                        break
                    if t == "M" and i + 2 < len(rest) and rest[i + 1] == "&" and rest[i + 2] == "F":
                        cat_start = i
                        break

                if cat_start is None:
                    actividade_tokens = rest[:class_start]
                    categorias_tokens = []
                else:
                    actividade_tokens = rest[:cat_start]
                    categorias_tokens = rest[cat_start:class_start]

                # remover "FPP" isolado no fim da actividade (aparece em alguns casos)
                if actividade_tokens and actividade_tokens[-1] == "FPP":
                    actividade_tokens = actividade_tokens[:-1]

                actividade = " ".join(actividade_tokens).strip()
                categorias = " ".join(categorias_tokens).strip()

                rows.append({
                    "Mes": current_month.title(),
                    "Dia": date,
                    "DIV": div,
                    "Actividade": actividade,
                    "Categorias": categorias,
                    "Classe": classe,
                    "Local_raw": local,
                    "Organizacao": organizacao,
                    "Data (mês + dia)": f"{current_month.title()} {date}",
                })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df[df["DIV"].isin(["ABS", "JOV"])].copy()
    df.drop_duplicates(inplace=True)

    month_order = {m.title(): i for i, m in enumerate(MONTHS, start=1)}
    df["Mes_ord"] = df["Mes"].map(month_order).fillna(99).astype(int)
    df.sort_values(["Mes_ord", "Dia", "DIV", "Actividade"], inplace=True)
    df.drop(columns=["Mes_ord"], inplace=True)

    return df


# ----------------------------
# UI
# ----------------------------
st.title("Calendário FPPadel — tabela dinâmica (ABS/JOV)")

with st.spinner("A detectar o PDF mais recente e a extrair dados..."):
    pdf_url = find_latest_calendar_pdf_url()
    pdf_name = os.path.basename(urlparse(pdf_url).path)
    pdf_bytes = download_pdf_bytes(pdf_url)
    df = parse_calendar_pdf(pdf_bytes)

st.caption(f"Versão carregada: **{pdf_name}**")
st.link_button("Abrir PDF", pdf_url)

if df.empty:
    st.error("Não consegui extrair linhas do PDF (o formato pode ter mudado).")
    st.stop()

# filtros
col1, col2, col3 = st.columns(3)

with col1:
    mes_opts = sorted(
        df["Mes"].unique(),
        key=lambda x: MONTHS.index(x.upper()) if x.upper() in MONTHS else 999
    )
    mes_sel = st.selectbox("Mês", options=["(Todos)"] + mes_opts)

with col2:
    div_sel = st.selectbox("DIV", options=["(Todos)", "ABS", "JOV"])

with col3:
    classes = sorted([c for c in df["Classe"].unique() if isinstance(c, str) and c.strip()])
    classe_sel = st.multiselect("Classe", options=classes, default=[])

filtered = df.copy()
if mes_sel != "(Todos)":
    filtered = filtered[filtered["Mes"] == mes_sel]
if div_sel != "(Todos)":
    filtered = filtered[filtered["DIV"] == div_sel]
if classe_sel:
    filtered = filtered[filtered["Classe"].isin(classe_sel)]

# juntar Local + Organização no campo Local (exibição)
def format_local(row):
    loc = (row.get("Local_raw") or "").strip()
    org = (row.get("Organizacao") or "").strip()
    if org and org.lower() != "nan":
        return f"{loc} — {org}"
    return loc

filtered["Local"] = filtered.apply(format_local, axis=1)

# link Google Maps
filtered["Mapa"] = filtered["Local"].apply(
    lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}"
)

# colunas finais (na ordem pedida + mapa)
filtered = filtered[[
    "Data (mês + dia)",
    "DIV",
    "Actividade",
    "Categorias",
    "Classe",
    "Local",
    "Mapa",
]]

st.subheader("Actividades")
st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Mapa": st.column_config.LinkColumn("Mapa", display_text="Abrir no Maps"),
    },
)

st.download_button(
    "Download CSV (filtrado)",
    data=filtered.drop(columns=["Mapa"]).to_csv(index=False).encode("utf-8"),
    file_name=f"calendario_fppadel_{pdf_name.replace('.pdf','')}.csv",
    mime="text/csv"
)
