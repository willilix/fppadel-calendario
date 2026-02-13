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

from points_calculator import render_points_calculator

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
st.set_page_config(page_title="Calendário FPPadel", page_icon="🎾", layout="wide")

# -------------------------------------------------
# PREMIUM CSS
# -------------------------------------------------
st.markdown("""
<style>

.block-container { padding-top: 1.5rem; max-width: 1120px; }

header { visibility: hidden; height: 0px; }

/* HERO HEADER */
.hero {
  border-radius: 28px;
  padding: 22px;
  margin-bottom: 18px;
  background: radial-gradient(1000px 500px at 20% 10%, rgba(10,132,255,0.18), transparent 60%),
              radial-gradient(800px 400px at 80% 20%, rgba(90,200,250,0.15), transparent 60%),
              rgba(255,255,255,0.85);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(17,17,17,0.08);
  box-shadow: 0 20px 50px rgba(0,0,0,0.08);
}

.hero-title {
  font-size: 1.6rem;
  font-weight: 800;
  margin-bottom: 4px;
}

.hero-sub {
  color: rgba(0,0,0,0.6);
  font-size: 0.95rem;
}

.pill {
  display:inline-block;
  padding:5px 12px;
  border-radius:999px;
  font-size:0.75rem;
  background:rgba(0,0,0,0.05);
  border:1px solid rgba(0,0,0,0.08);
  margin-right:6px;
  margin-top:8px;
}

/* Cards */
.metric {
  border-radius:18px;
  padding:14px;
  background:white;
  border:1px solid rgba(0,0,0,0.08);
  box-shadow:0 8px 25px rgba(0,0,0,0.05);
}

</style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# CONSTANTS
# -------------------------------------------------
HOME_URL = "https://fppadel.pt/"
WP_MEDIA_SEARCH = "https://fppadel.pt/wp-json/wp/v2/media"

MONTHS = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"
]
MONTH_TO_NUM = {m.title(): i for i, m in enumerate(MONTHS, start=1)}

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def month_sort_key(m: str) -> int:
    try:
        return MONTHS.index(m.upper())
    except ValueError:
        return 999

def _pick_highest_version(urls):
    def score(u):
        m = re.search(r"-(\d+)\.pdf$", u)
        return int(m.group(1)) if m else -1
    urls = list(set(urls))
    urls.sort(key=lambda u: (score(u), u), reverse=True)
    return urls[0]

def infer_year_from_pdf_url(pdf_url: str) -> int:
    m = re.search(r"/uploads/(\d{4})/", pdf_url)
    if m:
        return int(m.group(1))
    return dt.date.today().year

# -------------------------------------------------
# LOAD PDF
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
    return _pick_highest_version(candidates)

@st.cache_data(ttl=900)
def download_pdf_bytes(pdf_url: str):
    r = requests.get(pdf_url)
    r.raise_for_status()
    return r.content

# -------------------------------------------------
# NAVIGATION
# -------------------------------------------------
col_tabs, col_btn = st.columns([5,1])

with col_tabs:
    tab_cal, tab_pts = st.tabs(["📅 Calendário", "🧮 Pontos"])

with col_btn:
    st.link_button("🏆 Rankings", "https://tour.tiesports.com/fpp/weekly_rankings")

# -------------------------------------------------
# CALENDÁRIO
# -------------------------------------------------
with tab_cal:

    pdf_url = find_latest_calendar_pdf_url()
    pdf_name = os.path.basename(urlparse(pdf_url).path)
    year = infer_year_from_pdf_url(pdf_url)

    # ---------------- HERO HEADER ----------------
    col1, col2 = st.columns([1,6])

    with col1:
        st.image("armadura.png", width=100)

    with col2:
        st.markdown(f"""
        <div class="hero">
            <div class="hero-title">Calendário FPPadel</div>
            <div class="hero-sub">ABS e JOV • actualizado automaticamente • Maps</div>
            <div>
                <span class="pill">PDF: {pdf_name}</span>
                <span class="pill">Ano: {year}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.link_button("Abrir PDF original", pdf_url)

    pdf_bytes = download_pdf_bytes(pdf_url)

    st.success("Header premium activo com sucesso 🛡️")

# -------------------------------------------------
# PONTOS
# -------------------------------------------------
with tab_pts:
    render_points_calculator()
