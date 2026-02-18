import os
import re
import datetime as dt
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote_plus

import pandas as pd
import pdfplumber
import requests
import streamlit as st
from bs4 import BeautifulSoup

from modules.ui import render_global_ui, init_mobile_detection
from modules.calendar_tab import render_calendar
from modules.tournaments_tab import render_tournaments
from modules.points_tab import render_points
from modules.rankings_tab import render_rankings


# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA
# ---------------------------------------------------
st.set_page_config(
    page_title="FPPadel Calendário",
    page_icon="icon.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

render_global_ui(icon_path="icon.png", logo_path="armadura.png")
is_mobile = init_mobile_detection()


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


def _pick_highest_version(urls: list[str]) -> str:
    def score(u: str) -> int:
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
# DISCOVER LATEST PDF
# -------------------------------------------------
@st.cache_data(ttl=86400)
def find_latest_calendar_pdf_url() -> str:
    try:
        html = requests.get(HOME_URL, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = (a.get_text() or "").strip().lower()
            if "saber mais" in text and href.lower().endswith(".pdf") and "calend" in href.lower():
                candidates.append(urljoin(HOME_URL, href))

        if not candidates:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.lower().endswith(".pdf") and "calend" in href.lower():
                    candidates.append(urljoin(HOME_URL, href))

        if candidates:
            return _pick_highest_version(candidates)
    except Exception:
        pass

    raise RuntimeError("Não consegui encontrar o PDF do calendário.")


@st.cache_data(ttl=86400)
def download_pdf_bytes(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, timeout=30)
    r.raise_for_status()
    return r.content


# -------------------------------------------------
# PARSER
# -------------------------------------------------
@st.cache_data(ttl=86400)
def parse_calendar_pdf(pdf_bytes: bytes, year: int) -> pd.DataFrame:
    # mantém exatamente o teu parser atual
    # (não alterei nada aqui para não introduzir bugs)
    from modules.calendar_tab import parse_calendar_pdf as full_parser
    return full_parser(pdf_bytes, year)


def normalize_and_dedupe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()

    for col in out.columns:
        if out[col].dtype == object:
            out[col] = (
                out[col]
                .astype("string")
                .fillna("")
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"": pd.NA})
            )

    key_cols = [c for c in [
        "DIV", "Actividade", "Categorias", "Classe",
        "Local_pdf", "Organizacao_pdf", "Data_Inicio", "Data_Fim"
    ] if c in out.columns]

    if key_cols:
        tmp = out[key_cols].astype("string").fillna("").agg("|".join, axis=1).str.lower()
        out = out.loc[~tmp.duplicated(keep="first")].copy()

    return out


def build_local_dash_org(row):
    loc = str(row.get("Local_pdf") or "").strip()
    org = str(row.get("Organizacao_pdf") or "").strip()
    if loc and org:
        return f"{loc} - {org}"
    if loc:
        return loc
    if org:
        return org
    return ""


# -------------------------------------------------
# MAIN TABS
# -------------------------------------------------
tab_cal, tab_tour, tab_pts, tab_rank = st.tabs(
    ["📅 Calendário", "🎾 Torneios", "🧮 Pontos", "🏆 Rankings"]
)

with tab_cal:
    render_calendar(
        find_latest_calendar_pdf_url=find_latest_calendar_pdf_url,
        infer_year_from_pdf_url=infer_year_from_pdf_url,
        download_pdf_bytes=download_pdf_bytes,
        parse_calendar_pdf=parse_calendar_pdf,
        normalize_and_dedupe=normalize_and_dedupe,
        build_local_dash_org=build_local_dash_org,
        month_sort_key=month_sort_key,
        is_mobile=is_mobile,
    )

with tab_tour:
    render_tournaments(is_mobile=is_mobile)

with tab_pts:
    render_points()

with tab_rank:
    render_rankings()
