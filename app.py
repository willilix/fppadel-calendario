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

# -------------------------------------------------
# CONFIG
# -------------------------------------------------

st.set_page_config(
    page_title="Calendário FPPadel",
    page_icon="🎾",
    layout="wide"
)

# ------------------ CSS MODERNO ------------------

st.markdown("""
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 3rem;}

h1 {margin-bottom: 0.3rem;}
.sub {opacity: 0.75; margin-bottom: 1.5rem;}

.card {
  padding: 16px;
  border-radius: 16px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  margin-bottom: 14px;
}

.badge {
  display:inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.2);
  font-size: 0.75rem;
  margin-left: 6px;
}

.metric-card {
  padding: 14px;
  border-radius: 14px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# CONSTANTES
# -------------------------------------------------

HOME_URL = "https://fppadel.pt/"
WP_MEDIA_SEARCH = "https://fppadel.pt/wp-json/wp/v2/media"

MONTHS = [
    "JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO",
    "JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"
]
MONTH_TO_NUM = {m.title(): i for i, m in enumerate(MONTHS, start=1)}

# -------------------------------------------------
# MOBILE DETECTION
# -------------------------------------------------

if "is_mobile" not in st.session_state:
    st.session_state["is_mobile"] = False

components.html("""
<script>
const isMobile = window.matchMedia("(max-width: 768px)").matches;
window.parent.postMessage(
{ type: "streamlit:setSessionState", key: "is_mobile", value: isMobile },
"*");
</script>
""", height=0)

is_mobile = st.session_state.get("is_mobile", False)

# -------------------------------------------------
# UTILIDADES
# -------------------------------------------------

def class_badge(classe):
    c = (classe or "").lower()
    if "gold" in c or "50.000" in c: return "🥇"
    if "silver" in c: return "🥈"
    if "bronze" in c: return "🥉"
    if "continental" in c: return "🌍"
    if "10.000" in c: return "🔵"
    if "5.000" in c: return "🟢"
    if "2.000" in c: return "⚪"
    if "a definir" in c: return "❓"
    return ""

# -------------------------------------------------
# FETCH PDF
# -------------------------------------------------

@st.cache_data(ttl=900)
def find_latest_calendar_pdf_url():
    html = requests.get(HOME_URL).text
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf") and "calend" in href.lower():
            candidates.append(urljoin(HOME_URL, href))
    return sorted(candidates)[-1]

@st.cache_data(ttl=900)
def download_pdf_bytes(pdf_url):
    return requests.get(pdf_url).content

# -------------------------------------------------
# PARSER (VERSÃO COMPLETA COM LOCAL/ORGANIZAÇÃO)
# -------------------------------------------------

def parse_calendar_pdf(pdf_bytes):
    rows = []
    current_month = None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                up = line.upper()

                for m in MONTHS:
                    if up.startswith(m):
                        current_month = m
                        line = line[len(m):].strip()

                if not current_month:
                    continue

                if " ABS " in f" {line} " or " JOV " in f" {line} ":
                    div = "ABS" if " ABS " in f" {line} " else "JOV"

                    parts = re.split(r"\s{2,}", line)
                    parts = [p.strip() for p in parts if p.strip()]

                    date = parts[0] if len(parts) > 0 else ""
                    actividade = parts[1] if len(parts) > 1 else ""
                    categorias = parts[2] if len(parts) > 2 else ""
                    classe = parts[3] if len(parts) > 3 else ""
                    local = parts[5] if len(parts) > 5 else ""
                    org = parts[6] if len(parts) > 6 else ""

                    rows.append({
                        "Mes": current_month.title(),
                        "Dia": date,
                        "DIV": div,
                        "Actividade": actividade,
                        "Categorias": categorias,
                        "Classe": classe,
                        "Local": f"{local} - {org}" if org else local,
                        "Data (mês + dia)": f"{current_month.title()} {date}"
                    })

    return pd.DataFrame(rows)

# -------------------------------------------------
# HEADER
# -------------------------------------------------

st.title("🎾 Calendário FPPadel")
st.markdown('<div class="sub">Eventos ABS e JOV com actualização automática</div>', unsafe_allow_html=True)

pdf_url = find_latest_calendar_pdf_url()
pdf_name = os.path.basename(urlparse(pdf_url).path)
pdf_bytes = download_pdf_bytes(pdf_url)
df = parse_calendar_pdf(pdf_bytes)

st.caption(f"Versão do PDF: {pdf_name}")
st.link_button("Abrir PDF original", pdf_url)

# -------------------------------------------------
# FILTROS
# -------------------------------------------------

st.subheader("Filtros")

col1, col2, col3 = st.columns(3)

with col1:
    mes_sel = st.selectbox("Mês", ["(Todos)"] + sorted(df["Mes"].unique()))

with col2:
    div_sel = st.selectbox("DIV", ["(Todos)", "ABS", "JOV"])

with col3:
    classe_sel = st.multiselect("Classe", sorted(df["Classe"].unique()))

filtered = df.copy()

if mes_sel != "(Todos)":
    filtered = filtered[filtered["Mes"] == mes_sel]
if div_sel != "(Todos)":
    filtered = filtered[filtered["DIV"] == div_sel]
if classe_sel:
    filtered = filtered[filtered["Classe"].isin(classe_sel)]

# Google Maps
filtered["Mapa"] = filtered["Local"].apply(
    lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}"
)

filtered["Destaque"] = filtered["Classe"].apply(class_badge)

# -------------------------------------------------
# OUTPUT
# -------------------------------------------------

st.subheader("Actividades")

if is_mobile:
    for _, row in filtered.iterrows():
        st.markdown(f"""
        <div class="card">
        <div style="font-weight:600;font-size:1.05rem;">{row['Actividade']}</div>
        <div>📅 {row['Data (mês + dia)']} <span class="badge">{row['DIV']}</span></div>
        <div>Categorias: {row['Categorias']}</div>
        <div>Classe: {row['Classe']} {row['Destaque']}</div>
        <div>Local: {row['Local']}</div>
        <div style="margin-top:8px;">
        <a href="{row['Mapa']}" target="_blank">📍 Abrir no Maps</a>
        </div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.dataframe(
        filtered[[
            "Data (mês + dia)",
            "DIV",
            "Actividade",
            "Categorias",
            "Classe",
            "Local",
            "Mapa"
        ]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Mapa": st.column_config.LinkColumn("Mapa", display_text="Maps")
        }
    )
