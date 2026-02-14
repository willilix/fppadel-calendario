import os
import re
import base64
import datetime as dt
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote_plus

import pandas as pd
import pdfplumber
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

# 👇 points calculator sub-app
from points_calculator import render_points_calculator

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
st.set_page_config(page_title="Calendário FPPadel", page_icon="🎾", layout="wide")

# Apple Sports UI (CSS)
st.markdown("""
<style>
/* ===========================
   Apple Premium Dark (SaaS)
   =========================== */

/* Base layout */
:root{
  --bg0:#07070A;
  --bg1:#0B0B10;
  --card: rgba(18,18,26,0.74);
  --card2: rgba(18,18,26,0.62);
  --stroke: rgba(255,255,255,0.10);
  --stroke2: rgba(255,255,255,0.08);
  --text: rgba(237,237,243,0.96);
  --muted: rgba(237,237,243,0.62);
  --muted2: rgba(237,237,243,0.52);
  --blue: #0A84FF;
  --blueA: rgba(10,132,255,0.18);
  --shadow: 0 18px 60px rgba(0,0,0,0.58);
  --shadow2: 0 26px 85px rgba(0,0,0,0.72);
}

html, body, [class*="css"]{
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.block-container{
  padding-top: 1.05rem;
  padding-bottom: 3rem;
  max-width: 1120px;
  animation: appIn 260ms ease-out both;
}

header { visibility: hidden; height: 0px; }

/* App background */
.stApp{
  background:
    radial-gradient(1200px 680px at 50% -12%, rgba(10,132,255,0.18), rgba(0,0,0,0) 56%),
    radial-gradient(900px 600px at 12% 0%, rgba(255,255,255,0.04), rgba(0,0,0,0) 55%),
    linear-gradient(180deg, var(--bg1) 0%, var(--bg0) 100%);
  color: var(--text);
}

/* Typography */
h1, h2, h3 { letter-spacing: -0.02em; }
p, li, span { color: var(--text); }

/* Links */
a, a:visited { color: var(--blue) !important; text-decoration: none; }
a:hover { text-decoration: underline; }

/* --- Micro animations --- */
@keyframes appIn{
  from{ opacity:0; transform: translateY(8px); }
  to{ opacity:1; transform: translateY(0); }
}

@keyframes shimmer{
  0%{ background-position: 0% 50%; }
  100%{ background-position: 100% 50%; }
}

@media (prefers-reduced-motion: reduce){
  *{ animation:none !important; transition:none !important; }
}

/* Logo bar */
.logo-wrap{
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 6px;
  margin-bottom: 10px;
}

.logo-wrap img{
  display:block;
  height: 126px; /* metade do tamanho */
  width: auto;
  filter: drop-shadow(0 18px 40px rgba(0,0,0,0.55));
}

.logo-text{
  font-weight: 750;
  font-size: 1.05rem;
  color: rgba(237,237,243,0.70);
  text-align: center;
  line-height: 1.2;
  max-width: 520px;
}

@media (max-width: 520px){
  .logo-wrap{ gap: 12px; }
  .logo-wrap img{ height: 105px; }
  .logo-text{ font-size: 1.0rem; }
}

/* Top bar (glass) */
.topbar{
  background: linear-gradient(90deg, rgba(18,18,26,0.70), rgba(10,132,255,0.10), rgba(18,18,26,0.70));
  background-size: 200% 100%;
  animation: shimmer 9s ease-in-out infinite;
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--stroke2);
  border-radius: 20px;
  padding: 16px;
  margin-bottom: 14px;
  box-shadow: var(--shadow);
}

.top-title{
  font-weight: 850;
  font-size: 1.45rem;
  margin: 0;
  color: var(--text);
}

.top-sub{
  color: var(--muted);
  font-size: 0.95rem;
  margin-top: 4px;
}

/* Pills / chips */
.pill{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--stroke);
  background: rgba(255,255,255,0.06);
  font-size: 0.78rem;
  color: rgba(237,237,243,0.82);
}

/* Metric cards */
.metric{
  border-radius: 20px;
  background: var(--card);
  border: 1px solid var(--stroke2);
  box-shadow: var(--shadow);
  padding: 16px 16px;
  transition: transform 180ms ease, box-shadow 220ms ease, border-color 220ms ease, background 220ms ease;
}

.metric:hover{
  transform: translateY(-3px);
  border-color: rgba(10,132,255,0.35);
  box-shadow: var(--shadow2);
  background: rgba(20,20,30,0.78);
}

.metric .label{ color: var(--muted); font-size: 0.82rem; }
.metric .value{ font-weight: 850; font-size: 1.2rem; margin-top: 6px; color: var(--text); }
.metric .hint{ color: var(--muted2); font-size: 0.8rem; margin-top: 3px; }

/* Card blocks */
.card{
  border-radius: 24px;
  background: var(--card);
  border: 1px solid var(--stroke2);
  box-shadow: var(--shadow);
  padding: 18px;
  margin-bottom: 14px;
  transition: transform 180ms ease, box-shadow 220ms ease, border-color 220ms ease, background 220ms ease;
}

.card:hover{
  transform: translateY(-3px);
  border-color: rgba(10,132,255,0.35);
  box-shadow: var(--shadow2);
  background: rgba(20,20,30,0.78);
}

.card .title{ font-weight: 850; font-size: 1.06rem; color: var(--text); }
.card .row{ margin-top: 8px; font-size: 0.92rem; color: rgba(237,237,243,0.74); line-height: 1.35; }

/* Inputs and selects */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div{
  border-radius: 16px !important;
  border-color: rgba(255,255,255,0.14) !important;
  background: rgba(255,255,255,0.05) !important;
}

div[data-baseweb="select"] > div:hover,
div[data-baseweb="input"] > div:hover,
div[data-baseweb="textarea"] > div:hover{
  border-color: rgba(10,132,255,0.35) !important;
}

/* Buttons: iOS tap feedback */
.stButton button{
  border-radius: 16px !important;
  padding: 0.56rem 1.0rem !important;
  font-weight: 650 !important;
  transition: transform 120ms ease, filter 120ms ease, box-shadow 180ms ease;
  box-shadow: 0 10px 30px rgba(0,0,0,0.35);
}

.stButton button:active{
  transform: scale(0.985);
  filter: brightness(1.08);
}

/* Tabs: pill style */
.stTabs [data-baseweb="tab-list"]{ gap: 8px; }
.stTabs [data-baseweb="tab"]{
  border-radius: 999px !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  background: rgba(255,255,255,0.05) !important;
  padding: 8px 16px !important;
  color: rgba(237,237,243,0.76) !important;
  transition: transform 160ms ease, background 200ms ease, border-color 200ms ease;
}
.stTabs [aria-selected="true"]{
  background: rgba(10,132,255,0.18) !important;
  border-color: rgba(10,132,255,0.45) !important;
  color: rgba(237,237,243,0.98) !important;
  transform: translateY(-1px);
}

/* DataFrame */
[data-testid="stDataFrame"]{
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.10);
  box-shadow: 0 18px 60px rgba(0,0,0,0.52);
}

/* Hide Streamlit chrome bits (keep clean) */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ------------------------
# Helpers
# ------------------------
def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def sort_date_col(df: pd.DataFrame, col: str):
    if col in df.columns:
        try:
            return df.sort_values(col)
        except Exception:
            return df
    return df


# -------------------------------------------------
# PDF / DATA FETCHING
# -------------------------------------------------
CALENDAR_PDF_URL = "https://fppadel.pt/wp-content/uploads/2025/01/Calendario_FPPadel_2025.pdf"
CACHE_TTL_SECONDS = 60 * 60  # 1h


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_pdf_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def extract_events_from_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    rows = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            text = text.replace("–", "-").replace("—", "-")

            # Heurística para apanhar linhas com datas e eventos
            lines = [normalize_text(x) for x in text.split("\n") if normalize_text(x)]
            for ln in lines:
                # tenta identificar padrões tipo "01-02 Jan ..." / "01/02 ..." etc
                if re.search(r"\b(\d{1,2})[\/\-](\d{1,2})\b", ln):
                    # guarda linha bruta e deixa parse fino para abaixo
                    rows.append({"raw": ln})

    df_raw = pd.DataFrame(rows)
    if df_raw.empty:
        return pd.DataFrame()

    # Parse básico (adaptado ao teu formato)
    parsed = []
    for _, r in df_raw.iterrows():
        raw = r["raw"]

        # tenta extrair intervalo de datas
        m = re.search(r"(?P<d1>\d{1,2})[\/\-](?P<m1>\d{1,2})(?:\s*[-–]\s*(?P<d2>\d{1,2})[\/\-](?P<m2>\d{1,2}))?", raw)
        if not m:
            continue

        d1 = safe_int(m.group("d1"))
        m1 = safe_int(m.group("m1"))
        d2 = safe_int(m.group("d2"), d1)
        m2 = safe_int(m.group("m2"), m1)

        # remove o pedaço da data do texto para ficar com “resto”
        rest = raw[m.end():].strip(" -–\t")

        # tenta dividir: nome | local | categoria etc (depende do teu PDF)
        # fallback: guarda tudo em "Evento"
        parsed.append({
            "Data_Inicio_D": d1,
            "Data_Inicio_M": m1,
            "Data_Fim_D": d2,
            "Data_Fim_M": m2,
            "Linha": raw,
            "Evento": rest
        })

    df = pd.DataFrame(parsed)
    if df.empty:
        return df

    # Tenta criar uma data "aprox" (ano corrente) só para ordenar / filtrar
    current_year = dt.datetime.now().year
    def to_dt(row):
        try:
            return dt.date(current_year, int(row["Data_Inicio_M"]), int(row["Data_Inicio_D"]))
        except Exception:
            return None

    df["Data"] = df.apply(to_dt, axis=1)
    df = df.dropna(subset=["Data"]).reset_index(drop=True)
    df = df.sort_values("Data").reset_index(drop=True)
    return df


# -------------------------------------------------
# UI HEADER
# -------------------------------------------------
st.markdown(
    """
<div class="logo-wrap">
  <img src="https://raw.githubusercontent.com/streamlit/streamlit/develop/examples/data/logo.png" alt="logo" />
  <div class="logo-text">
    Calendário de Torneios FPPadel — versão premium
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="topbar">
  <div class="top-title">Calendário FPPadel</div>
  <div class="top-sub">Eventos ABS/JOV extraídos automaticamente do PDF • filtros • export CSV</div>
</div>
""",
    unsafe_allow_html=True,
)

# -------------------------------------------------
# LOAD DATA
# -------------------------------------------------
with st.spinner("A carregar calendário..."):
    try:
        pdf_bytes = fetch_pdf_bytes(CALENDAR_PDF_URL)
        df = extract_events_from_pdf(pdf_bytes)
    except Exception as e:
        st.error(f"Não foi possível carregar/extrair o PDF: {e}")
        df = pd.DataFrame()

# -------------------------------------------------
# MAIN UI
# -------------------------------------------------
tabs = st.tabs(["📅 Calendário", "🎯 Pontos", "🏆 Rankings"])

# ------------------------
# Tab: Calendário
# ------------------------
with tabs[0]:
    if df.empty:
        st.info("Não foram encontrados eventos no PDF.")
    else:
        # Métricas rápidas
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                f"""
<div class="metric">
  <div class="label">Total de eventos</div>
  <div class="value">{len(df)}</div>
  <div class="hint">Extraídos automaticamente</div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c2:
            first_date = df["Data"].min()
            st.markdown(
                f"""
<div class="metric">
  <div class="label">Próximo evento</div>
  <div class="value">{first_date.strftime('%d/%m/%Y') if pd.notna(first_date) else "-"}</div>
  <div class="hint">Ordenado por data</div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c3:
            last_date = df["Data"].max()
            st.markdown(
                f"""
<div class="metric">
  <div class="label">Último evento</div>
  <div class="value">{last_date.strftime('%d/%m/%Y') if pd.notna(last_date) else "-"}</div>
  <div class="hint">Fim do calendário</div>
</div>
""",
                unsafe_allow_html=True,
            )

        st.write("")

        # Filtros (mantidos simples para não partir nada)
        colA, colB = st.columns([2, 1])
        with colA:
            q = st.text_input("Pesquisar (nome/local/categoria)", value="", placeholder="Ex: Lisboa, ABS, Open, ...")
        with colB:
            month = st.selectbox("Mês", ["Todos"] + [f"{i:02d}" for i in range(1, 13)], index=0)

        df_view = df.copy()
        if q.strip():
            qq = q.strip().lower()
            df_view = df_view[df_view.apply(lambda r: qq in str(r).lower(), axis=1)]

        if month != "Todos":
            df_view = df_view[df_view["Data"].apply(lambda d: f"{d.month:02d}" == month)]

        df_view = df_view.sort_values("Data")

        st.dataframe(
            df_view[["Data", "Evento", "Linha"]].rename(columns={"Linha": "Detalhe"}),
            use_container_width=True,
            hide_index=True,
        )

        # Export CSV
        csv = df_view.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Exportar CSV",
            data=csv,
            file_name="calendario_fppadel.csv",
            mime="text/csv",
        )

# ------------------------
# Tab: Pontos (sub-app)
# ------------------------
with tabs[1]:
    render_points_calculator()

# ------------------------
# Tab: Rankings (placeholder / futura integração)
# ------------------------
with tabs[2]:
    st.markdown(
        """
<div class="card">
  <div class="title">Rankings</div>
  <div class="row">Esta secção pode ser ligada ao site de rankings para pesquisa por nome/licença e mostrar pontos, com cache e paginação.</div>
  <div class="row">Se quiseres, eu integro já a pesquisa automática e deixo isto “nível app”.</div>
</div>
""",
        unsafe_allow_html=True,
    )
