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
# DATE RANGE PARSER (helper do calendário)
# -------------------------------------------------
def parse_day_range_to_dates(day_text: str, month_num: int, year: int):
    """Converte 'Dia' do PDF (ex: '3-5', '3 a 5', '3/5', '3') em (data_inicio, data_fim)"""
    day_text = (day_text or "").strip().lower()
    nums = [int(n) for n in re.findall(r"\d{1,2}", day_text)]
    if not nums:
        return None, None

    d1 = min(nums)
    d2 = max(nums)

    def safe_date(d: int):
        try:
            return dt.date(year, month_num, d)
        except Exception:
            return None

    start = safe_date(d1)
    end = safe_date(d2)

    # Se por alguma razão o fim ficar antes do início (caso raro), força para o início
    if start and end and end < start:
        end = start

    return start, end



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
# PARSER (robusto: LOCAL/ORGANIZAÇÃO por coordenadas)
# -------------------------------------------------
@st.cache_data(ttl=86400)
def parse_calendar_pdf(pdf_bytes: bytes, year: int) -> pd.DataFrame:
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
                if "MÊS" in up and "ACTIVIDADES" in up and "DIV" in up:
                    continue
                if up.startswith("CALEND"):
                    continue

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

                div_idx = None
                for i, t in enumerate(tokens):
                    if t in ("ABS", "JOV"):
                        div_idx = i
                        break
                if div_idx is None:
                    continue
                div = tokens[div_idx]

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

                euro_idx = None
                for i, t in enumerate(rest):
                    if "€" in t:
                        euro_idx = i
                        break

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
                    if euro_idx is not None and euro_idx + 1 < len(rest):
                        local_col = rest[euro_idx + 1]
                        org_col = " ".join(rest[euro_idx + 2:]).strip() if euro_idx + 2 < len(rest) else ""

                month_title = current_month.title()
                month_num = MONTH_TO_NUM.get(month_title)
                start_date, end_date = (None, None)
                if month_num:
                    start_date, end_date = parse_day_range_to_dates(day_text, month_num, year)

                rows_out.append({
                    "Mes": month_title,
                    "Dia": day_text,
                    "DIV": div,
                    "Actividade": actividade,  # mantido internamente (não mostramos)
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
