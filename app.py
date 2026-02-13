import os
import re
import datetime as dt
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote_plus

import pandas as pd
import pdfplumber
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

HOME_URL = "https://fppadel.pt/"
WP_MEDIA_SEARCH = "https://fppadel.pt/wp-json/wp/v2/media"

MONTHS = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"
]
MONTH_TO_NUM = {m.title(): i for i, m in enumerate(MONTHS, start=1)}

st.set_page_config(page_title="Calendário FPPadel", layout="wide")


# ----------------------------
# Mobile detection (best-effort)
# ----------------------------
if "is_mobile" not in st.session_state:
    st.session_state["is_mobile"] = False

components.html(
    """
    <script>
      try {
        const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
        window.parent.postMessage(
          { type: "streamlit:setSessionState", key: "is_mobile", value: !!isMobile },
          "*"
        );
      } catch (e) {}
    </script>
    """,
    height=0,
)

is_mobile = bool(st.session_state.get("is_mobile", False))


# ----------------------------
# Utilidades
# ----------------------------
def _pick_highest_version(urls: list[str]) -> str:
    """Escolhe o URL com maior sufixo '-<n>.pdf'."""
    def score(u: str) -> int:
        m = re.search(r"-(\d+)\.pdf$", u)
        return int(m.group(1)) if m else -1

    urls = list(set(urls))
    urls.sort(key=lambda u: (score(u), u), reverse=True)
    return urls[0]


def infer_year_from_pdf_url(pdf_url: str) -> int:
    """Tenta inferir o ano pelo caminho /wp-content/uploads/YYYY/..."""
    m = re.search(r"/uploads/(\d{4})/", pdf_url)
    if m:
        return int(m.group(1))
    return dt.date.today().year


def parse_day_range_to_dates(day_text: str, month_num: int, year: int) -> tuple[dt.date | None, dt.date | None]:
    """
    Converte textos tipo "4 a 8", "6-8", "27", "27 a 1" (cruza mês se fim < início)
    para (data_inicio, data_fim).
    """
    if not day_text:
        return None, None

    nums = re.findall(r"\d{1,2}", day_text)
    if not nums:
        return None, None

    start_day = int(nums[0])
    end_day = int(nums[-1]) if len(nums) > 1 else start_day

    try:
        start_date = dt.date(year, month_num, start_day)
    except ValueError:
        return None, None

    end_month = month_num
    end_year = year
    if end_day < start_day:
        if month_num == 12:
            end_month = 1
            end_year = year + 1
        else:
            end_month = month_num + 1

    try:
        end_date = dt.date(end_year, end_month, end_day)
    except ValueError:
        end_date = start_date

    return start_date, end_date


def normalize_text(s: str) -> str:
    return (s or "").strip()


def class_badge(classe: str) -> str:
    c = (classe or "").lower()
    if "gold" in c or "50.000" in c:
        return "🥇"
    if "silver" in c:
        return "🥈"
    if "bronze" in c:
        return "🥉"
    if "continental" in c or "promises" in c:
        return "🌍"

    m = re.search(r"(\d{1,3}(?:\.\d{3})+)", classe or "")
    value = None
    if m:
        value = int(m.group(1).replace(".", ""))

    if value is not None:
        if value >= 10000:
            return "🔵"
        if value >= 5000:
            return "🟢"
        return "⚪"

    if "a definir" in c:
        return "❓"

    return ""


# ----------------------------
# Descobrir PDF mais recente
# ----------------------------
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


# ----------------------------
# Parsing PDF -> DataFrame (LOCAL/ORGANIZAÇÃO por coordenadas)
# ----------------------------
def parse_calendar_pdf(pdf_bytes: bytes, year: int) -> pd.DataFrame:
    """
    Extrai:
      - Data (mês+dia)
      - DIV (ABS/JOV)
      - Actividade
      - Categorias
      - Classe
      - LOCAL (da coluna LOCAL do PDF)
      - ORGANIZAÇÃO (da coluna ORGANIZAÇÃO do PDF)

    Usa coordenadas do cabeçalho para separar LOCAL/ORGANIZAÇÃO mesmo com várias palavras.
    """

    def looks_like_money(tok: str) -> bool:
        return bool(re.fullmatch(r"[´']?\d{1,3}(?:\.\d{3})*(?:,\d+)?", tok))

    def is_category_token(tok: str) -> bool:
        return bool(re.fullmatch(r"(F|M|S)\d{1,2}", tok)) or tok in {"VET", "FIP"}

    def group_words_into_rows(words, y_tol=3):
        rows = []
        for w in sorted(words, key=lambda x: (x["top"], x["x0"])):
            placed = False
            for r in rows:
                if abs(w["top"] - r["y"]) <= y_tol:
                    r["words"].append(w)
                    r["y"] = (r["y"] * (len(r["words"]) - 1) + w["top"]) / len(r["words"])
                    placed = True
                    break
            if not placed:
                rows.append({"y": w["top"], "words": [w]})
        for r in rows:
            r["words"] = sorted(r["words"], key=lambda x: x["x0"])
        return rows

    rows_out = []
    current_month = None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True) or []
            if not words:
                continue

            line_rows = group_words_into_rows(words, y_tol=3)

            # detectar posições x das colunas LOCAL e ORGANIZAÇÃO pelo cabeçalho
            x_local = None
            x_org = None

            for lr in line_rows:
                line_text = " ".join(w["text"] for w in lr["words"]).strip()
                up = line_text.upper()
                if ("LOCAL" in up) and ("ORGAN" in up) and ("DIV" in up) and ("ACTIV" in up):
                    for w in lr["words"]:
                        t = w["text"].upper()
                        if t == "LOCAL":
                            x_local = w["x0"]
                        if t.startswith("ORGAN"):
                            x_org = w["x0"]

            for lr in line_rows:
                line_text = " ".join(w["text"] for w in lr["words"]).strip()
                if not line_text:
                    continue

                up = line_text.upper()

                # ignorar cabeçalhos
                if "MÊS" in up and "ACTIVIDADES" in up and "DIV" in up:
                    continue
                if up.startswith("CALEND"):
                    continue

                # detectar mês (linha só com mês ou mês no início)
                month_found = None
                for m in MONTHS:
                    if up == m:
                        month_found = m
                        break
                    if up.startswith(m + " "):
                        month_found = m
                        line_text = line_text[len(m):].strip()
                        break

                if month_found:
                    current_month = month_found
                    if up == month_found:
                        continue

                if not current_month:
                    continue

                tokens = line_text.split()

                # encontrar DIV
                div_idx = None
                for i, t in enumerate(tokens):
                    if t in ("ABS", "JOV"):
                        div_idx = i
                        break
                if div_idx is None:
                    continue

                div = tokens[div_idx]

                # data (texto)
                pre = tokens[:div_idx]
                tipo_set = {"CIR", "FPP", "FOR", "INT"}
                if len(pre) >= 2 and pre[-2] in tipo_set:
                    day_text = " ".join(pre[:-2]).strip()
                elif len(pre) >= 1 and pre[-1] in tipo_set:
                    day_text = " ".join(pre[:-1]).strip()
                else:
                    day_text = " ".join(pre).strip()

                rest = tokens[div_idx + 1:]
                if not rest:
                    continue

                # localizar token com €
                euro_idx = None
                for i, t in enumerate(rest):
                    if "€" in t:
                        euro_idx = i
                        break

                # classe
                class_end = euro_idx if euro_idx is not None else len(rest)
                classe = ""
                class_start = None

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

                if actividade_tokens and actividade_tokens[-1] == "FPP":
                    actividade_tokens = actividade_tokens[:-1]

                actividade = " ".join(actividade_tokens).strip()
                categorias = " ".join(categorias_tokens).strip()

                # LOCAL e ORGANIZAÇÃO por coordenadas
                local_col = ""
                org_col = ""
                if x_local is not None and x_org is not None:
                    margin = 2.0
                    local_words = [
                        w["text"] for w in lr["words"]
                        if (w["x0"] >= x_local - margin) and (w["x0"] < x_org - margin)
                    ]
                    org_words = [
                        w["text"] for w in lr["words"]
                        if (w["x0"] >= x_org - margin)
                    ]
                    local_col = " ".join(local_words).strip()
                    org_col = " ".join(org_words).strip()

                    if local_col.upper() == "LOCAL":
                        local_col = ""
                    if org_col.upper().startswith("ORGAN"):
                        org_col = ""
                else:
                    # fallback (menos preciso)
                    if euro_idx is not None and euro_idx + 1 < len(rest):
                        local_col = rest[euro_idx + 1]
                        org_col = " ".join(rest[euro_idx + 2:]).strip() if euro_idx + 2 < len(rest) else ""

                month_title = current_month.title()
                month_num = MONTH_TO_NUM.get(month_title, None)

                start_date, end_date = (None, None)
                if month_num:
                    start_date, end_date = parse_day_range_to_dates(day_text, month_num, year)

                rows_out.append({
                    "Mes": month_title,
                    "Dia": day_text,
                    "DIV": div,
                    "Actividade": actividade,
                    "Categorias": categorias,
                    "Classe": classe,
                    "Local_pdf": local_col,
                    "Organizacao_pdf": org_col,
                    "Data_Inicio": start_date,
                    "Data_Fim": end_date,
                    "Data (mês + dia)": f"{month_title} {day_text}",
                })

    df = pd.DataFrame(rows_out)
    if df.empty:
        return df

    df = df[df["DIV"].isin(["ABS", "JOV"])].copy()
    df.drop_duplicates(inplace=True)

    df["SortDate"] = df["Data_Inicio"].fillna(pd.Timestamp.max.date())
    df.sort_values(["SortDate", "DIV", "Actividade"], inplace=True)
    df.drop(columns=["SortDate"], inplace=True)

    return df


# ----------------------------
# UI
# ----------------------------
st.title("Calendário FPPadel — tabela dinâmica (ABS/JOV)")

with st.container():
    left, right = st.columns([1, 1])
    with right:
        if st.button("🔄 Forçar actualizar agora"):
            st.cache_data.clear()
            st.rerun()

with st.spinner("A detectar o PDF mais recente e a extrair dados..."):
    pdf_url = find_latest_calendar_pdf_url()
    pdf_name = os.path.basename(urlparse(pdf_url).path)
    year = infer_year_from_pdf_url(pdf_url)
    pdf_bytes = download_pdf_bytes(pdf_url)
    df = parse_calendar_pdf(pdf_bytes, year=year)

# indicador de mudança de versão
last_key = "last_pdf_name"
prev = st.session_state.get(last_key)
st.session_state[last_key] = pdf_name
if prev and prev != pdf_name:
    st.success(f"🟢 Nova versão detectada! Antes: {prev} | Agora: {pdf_name}")

st.caption(f"Versão carregada: **{pdf_name}** (Ano inferido: {year})")
st.link_button("Abrir PDF", pdf_url)

if df.empty:
    st.error("Não consegui extrair linhas do PDF (o formato pode ter mudado).")
    st.stop()

# ----------------------------
# Filtros (mobile friendly)
# ----------------------------
if is_mobile:
    with st.expander("🔎 Filtros", expanded=False):
        mes_opts = sorted(df["Mes"].unique(), key=lambda x: MONTHS.index(x.upper()) if x.upper() in MONTHS else 999)
        mes_sel = st.selectbox("Mês", options=["(Todos)"] + mes_opts)
        div_sel = st.selectbox("DIV", options=["(Todos)", "ABS", "JOV"])
        classes = sorted([c for c in df["Classe"].unique() if isinstance(c, str) and c.strip()])
        classe_sel = st.multiselect("Classe", options=classes, default=[])
        quick = st.selectbox("Filtro rápido (datas)", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"])
        search = st.text_input("Pesquisa")
else:
    st.subheader("Filtros")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        mes_opts = sorted(df["Mes"].unique(), key=lambda x: MONTHS.index(x.upper()) if x.upper() in MONTHS else 999)
        mes_sel = st.selectbox("Mês", options=["(Todos)"] + mes_opts)
    with c2:
        div_sel = st.selectbox("DIV", options=["(Todos)", "ABS", "JOV"])
    with c3:
        classes = sorted([c for c in df["Classe"].unique() if isinstance(c, str) and c.strip()])
        classe_sel = st.multiselect("Classe", options=classes, default=[])
    with c4:
        quick = st.selectbox("Filtro rápido (datas)", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"])
    search = st.text_input("Pesquisa (ex: Lisboa, FIP, S14, Madeira, nome do clube...)")

filtered = df.copy()

if mes_sel != "(Todos)":
    filtered = filtered[filtered["Mes"] == mes_sel]
if div_sel != "(Todos)":
    filtered = filtered[filtered["DIV"] == div_sel]
if classe_sel:
    filtered = filtered[filtered["Classe"].isin(classe_sel)]

today = dt.date.today()
if quick != "(Nenhum)":
    if quick == "Este mês":
        start = dt.date(today.year, today.month, 1)
        if today.month == 12:
            end = dt.date(today.year, 12, 31)
        else:
            end = dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)
    elif quick == "Próximos 7 dias":
        start = today
        end = today + dt.timedelta(days=7)
    else:
        start = today
        end = today + dt.timedelta(days=30)

    filtered = filtered[
        (filtered["Data_Inicio"].notna()) &
        (filtered["Data_Fim"].notna()) &
        (filtered["Data_Inicio"] <= end) &
        (filtered["Data_Fim"] >= start)
    ]

if search.strip():
    q = search.strip().lower()
    cols = ["Data (mês + dia)", "DIV", "Actividade", "Categorias", "Classe", "Local_pdf", "Organizacao_pdf", "Mes"]
    mask = False
    for col in cols:
        mask = mask | filtered[col].astype(str).str.lower().str.contains(q, na=False)
    filtered = filtered[mask]

# ----------------------------
# Coluna Local = "LOCAL - ORGANIZAÇÃO" + Maps + Destaque
# ----------------------------
def build_local_dash_org(row):
    loc = normalize_text(row.get("Local_pdf"))
    org = normalize_text(row.get("Organizacao_pdf"))

    if loc and org and org.lower() != "nan":
        return f"{loc} - {org}"
    if loc:
        return loc
    if org and org.lower() != "nan":
        return org
    return ""

filtered["Local"] = filtered.apply(build_local_dash_org, axis=1)
filtered["Destaque"] = filtered["Classe"].apply(class_badge)
filtered["Mapa"] = filtered["Local"].apply(
    lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}"
)

out = filtered[[
    "Data (mês + dia)",
    "DIV",
    "Actividade",
    "Categorias",
    "Classe",
    "Local",
    "Destaque",
    "Mapa",
]].copy()

# ----------------------------
# Output (tabela desktop, cartões mobile)
# ----------------------------
st.subheader("Actividades")

if is_mobile:
    for _, row in out.iterrows():
        st.markdown(f"### {row['Actividade']}")
        st.markdown(f"**📅 {row['Data (mês + dia)']}** · **{row['DIV']}**")
        st.markdown(f"**Categorias:** {row['Categorias']}")
        st.markdown(f"**Classe:** {row['Classe']} {row['Destaque']}")
        st.markdown(f"**Local:** {row['Local']}")
        st.markdown(f"[📍 Abrir no Maps]({row['Mapa']})")
        st.divider()
else:
    st.dataframe(
        out,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Mapa": st.column_config.LinkColumn("Mapa", display_text="Abrir no Maps"),
            "Destaque": st.column_config.TextColumn("Destaque"),
        },
    )

st.download_button(
    "Download CSV (filtrado)",
    data=out.drop(columns=["Mapa"]).to_csv(index=False).encode("utf-8"),
    file_name=f"calendario_fppadel_{pdf_name.replace('.pdf','')}.csv",
    mime="text/csv"
)
