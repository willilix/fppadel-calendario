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

# CSS Premium UI
st.markdown("""
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 3rem;}

h1 {font-size: 2rem; margin-bottom: 0.2rem;}
.sub {opacity: 0.8; font-size: 0.95rem; margin-bottom: 1.5rem;}

.card {
    padding: 16px 18px;
    border-radius: 18px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 14px;
}

.small {opacity: 0.85; font-size: 0.9rem;}

.badge {
    display:inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.2);
    font-size: 0.8rem;
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
    "*"
  );
</script>
""", height=0)

is_mobile = st.session_state.get("is_mobile", False)

# -------------------------------------------------
# UTILIDADES
# -------------------------------------------------

def _pick_highest_version(urls):
    def score(u):
        m = re.search(r"-(\d+)\.pdf$", u)
        return int(m.group(1)) if m else -1
    urls = list(set(urls))
    urls.sort(key=lambda u: (score(u), u), reverse=True)
    return urls[0]

def infer_year_from_pdf_url(pdf_url):
    m = re.search(r"/uploads/(\d{4})/", pdf_url)
    if m:
        return int(m.group(1))
    return dt.date.today().year

def class_badge(classe):
    c = (classe or "").lower()
    if "gold" in c or "50.000" in c: return "🥇"
    if "silver" in c: return "🥈"
    if "bronze" in c: return "🥉"
    if "continental" in c: return "🌍"
    if "10.000" in c: return "🔵"
    if "5.000" in c: return "🟢"
    if "2.000" in c: return "⚪"
    return ""

# -------------------------------------------------
# FETCH PDF
# -------------------------------------------------

@st.cache_data(ttl=900)
def find_latest_calendar_pdf_url():
    try:
        html = requests.get(HOME_URL, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().endswith(".pdf") and "calend" in href.lower():
                candidates.append(urljoin(HOME_URL, href))
        if candidates:
            return _pick_highest_version(candidates)
    except:
        pass

    found = []
    for term in ["CALENDARIO-ACTIVIDADES"]:
        try:
            r = requests.get(WP_MEDIA_SEARCH, params={"search": term}, timeout=20)
            for it in r.json():
                src = (it.get("source_url") or "").strip()
                if src.lower().endswith(".pdf"):
                    found.append(src)
        except:
            continue

    return _pick_highest_version(found)

@st.cache_data(ttl=900)
def download_pdf_bytes(pdf_url):
    return requests.get(pdf_url).content

# -------------------------------------------------
# PARSER SIMPLIFICADO (mantém robustez actual)
# -------------------------------------------------

def parse_calendar_pdf(pdf_bytes, year):
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
                    parts = line.split()
                    div = "ABS" if " ABS " in f" {line} " else "JOV"

                    date = parts[0]
                    actividade = line.split(div)[1].strip()

                    rows.append({
                        "Mes": current_month.title(),
                        "Dia": date,
                        "DIV": div,
                        "Actividade": actividade,
                        "Categorias": "",
                        "Classe": "",
                        "Local": "",
                        "Data (mês + dia)": f"{current_month.title()} {date}",
                    })

    df = pd.DataFrame(rows)
    return df

# -------------------------------------------------
# HEADER
# -------------------------------------------------

st.markdown("## 🎾 Calendário FPPadel")
st.markdown('<div class="sub">Eventos ABS e JOV sempre actualizados automaticamente</div>', unsafe_allow_html=True)

with st.spinner("A carregar calendário mais recente..."):
    pdf_url = find_latest_calendar_pdf_url()
    pdf_name = os.path.basename(urlparse(pdf_url).path)
    year = infer_year_from_pdf_url(pdf_url)
    pdf_bytes = download_pdf_bytes(pdf_url)
    df = parse_calendar_pdf(pdf_bytes, year)

st.caption(f"Versão do PDF: {pdf_name}")
st.link_button("Abrir PDF original", pdf_url)

# -------------------------------------------------
# MÉTRICAS
# -------------------------------------------------

col1, col2, col3 = st.columns(3)

col1.metric("Total Eventos", len(df))
col2.metric("Mês Actual", dt.date.today().strftime("%B"))
col3.metric("Ano", year)

st.divider()

# -------------------------------------------------
# OUTPUT
# -------------------------------------------------

if df.empty:
    st.warning("Sem dados extraídos.")
    st.stop()

if is_mobile:
    for _, row in df.iterrows():
        st.markdown(f"""
        <div class="card">
            <div style="font-weight:600;font-size:1.05rem;">{row['Actividade']}</div>
            <div class="small">📅 {row['Data (mês + dia)']} 
            <span class="badge">{row['DIV']}</span></div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.dataframe(df, use_container_width=True, hide_index=True)
