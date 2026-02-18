from modules.ui import render_global_ui, init_mobile_detection

from modules.points_tab import render_points
from modules.rankings_tab import render_rankings

from modules.calendar_tab import render_calendar

from modules.tournaments_tab import render_tournaments

import os
import re
import base64
import datetime as dt
from io import BytesIO
from urllib.parse import urljoin, urlparse, quote_plus
import json

import pandas as pd
import pdfplumber
import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
import uuid
import io

# 👇 points calculator sub-app
from points_calculator import render_points_calculator



# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA (SÓ UMA VEZ)
# ---------------------------------------------------
st.set_page_config(
    page_title="FPPadel Calendário",
    page_icon="icon.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

render_global_ui(icon_path="icon.png", logo_path="armadura.png")
is_mobile = init_mobile_detection()

def set_ios_home_icon(path="icon.png"):
    if not os.path.exists(path):
        return

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

# --- Restore active main tab across reruns (keeps native st.tabs look) ---
def _remember_tab_in_url(tab_slug: str):
    """Persist selected main tab in the URL so we can restore it after reruns."""
    try:
        st.query_params["tab"] = tab_slug
    except Exception:
        pass

def _inject_tab_restorer_js():
    """Inject JS that auto-clicks the native Streamlit tab matching ?tab=..."""
    try:
        tab = st.query_params.get("tab")
    except Exception:
        tab = None
    if not tab:
        return

    label_map = {
        "calendario": "Calendário",
        "torneios": "Torneios",
        "pontos": "Pontos",
        "rankings": "Rankings",
    }
    target_label = label_map.get(str(tab))
    if not target_label:
        return

    components.html(
        f"""
        <script>
        (function() {{
          const label = {json.dumps(target_label)};
          function clickTab() {{
            const tabs = Array.from(document.querySelectorAll('[data-testid="stTab"]'));
            for (const t of tabs) {{
              const txt = (t.innerText || "").trim();
              if (txt.includes(label)) {{
                t.click();
                return true;
              }}
            }}
            return false;
          }}

          let tries = 0;
          const iv = setInterval(() => {{
            tries += 1;
            if (clickTab() || tries > 25) {{
              clearInterval(iv);
            }}
          }}, 200);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


# ---------------------------------------------------
# A PARTIR DAQUI MANTÉM O TEU CÓDIGO ORIGINAL
# (lógica calendário, PDF parsing, filtros, etc.)
# ---------------------------------------------------

# ⚠️ NÃO ALTERAR NADA ABAIXO DESTE PONTO
# Cola aqui exatamente o resto do teu código actual



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

def parse_day_range_to_dates(day_text: str, month_num: int, year: int):
    nums = re.findall(r"\d{1,2}", day_text or "")
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

import pandas as pd
import re

def normalize_text(s) -> str:
    if s is None or pd.isna(s):
        return ""
    s = str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_and_dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Limpeza leve: normaliza espaços e remove duplicados de forma estável."""
    if df is None or df.empty:
        return df

    out = df.copy()

    # Normalização de texto (trim + colapsar múltiplos espaços)
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

    # Dedupe por campos estruturais (sem alterar o layout final)
    key_cols = [c for c in [
        "DIV", "Actividade", "Categorias", "Classe",
        "Local_pdf", "Organizacao_pdf", "Data_Inicio", "Data_Fim"
    ] if c in out.columns]

    if key_cols:
        # chave estável para tolerar NaNs
        tmp = out[key_cols].astype("string").fillna("").agg("|".join, axis=1).str.lower()
        out = out.loc[~tmp.duplicated(keep="first")].copy()

    return out

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

    found = []
    for term in ["CALENDARIO-ACTIVIDADES-PROVISORIO", "RG-01-CALENDARIO-ACTIVIDADES", "CALENDARIO-ACTIVIDADES"]:
        try:
            r = requests.get(WP_MEDIA_SEARCH, params={"search": term, "per_page": 100}, timeout=20)
            if r.status_code != 200:
                continue
            for it in r.json():
                src = (it.get("source_url") or "").strip()
                if src.lower().endswith(".pdf") and "calend" in src.lower():
                    found.append(src)
        except Exception:
            continue

    if not found:
        raise RuntimeError("Não consegui encontrar o PDF do calendário (home + WP media falharam).")

    return _pick_highest_version(found)

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

# -------------------------------------------------
# BUILD DISPLAY FIELDS + METRICS
# -------------------------------------------------
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

import pandas as pd
import datetime as dt

def compute_metrics(view):
    global df

    # Garantir coluna Tipo
    if "Tipo" not in df.columns:
        for alt in ["TIPO", "tipo", "Categoria", "CATEGORIA", "Escalao", "Escalão"]:
            if alt in df.columns:
                df = df.rename(columns={alt: "Tipo"})
                break
    if "Tipo" not in df.columns:
        return 0, None, 0

    # ✅ Filtro tolerante
    tipo_norm = df["Tipo"].astype(str).str.upper().str.strip()
    view_norm = str(view).upper().strip()
    df_view = df[tipo_norm.str.contains(view_norm, na=False)].copy()

    total = len(df_view)

    # Datas
    if "Data_Inicio" in df_view.columns:
        df_view["Data_Inicio"] = pd.to_datetime(df_view["Data_Inicio"], errors="coerce")
    if "Data_Fim" in df_view.columns:
        df_view["Data_Fim"] = pd.to_datetime(df_view["Data_Fim"], errors="coerce")

    today = dt.date.today()

    # Próximo evento
    next_date = None
    if not df_view.empty and "Data_Inicio" in df_view.columns:
        future = df_view[
            df_view["Data_Inicio"].notna() &
            (df_view["Data_Inicio"].dt.date >= today)
        ]
        if not future.empty:
            sort_cols = [c for c in ["Data_Inicio", "DIV", "Actividade"] if c in future.columns]
            if sort_cols:
                future = future.sort_values(sort_cols)
            next_date = future.iloc[0]["Data_Inicio"]

    # Eventos deste mês
    start_month = dt.date(today.year, today.month, 1)
    if today.month == 12:
        end_month = dt.date(today.year, 12, 31)
    else:
        end_month = dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)

    if "Data_Inicio" in df_view.columns and "Data_Fim" in df_view.columns:
        this_month = df_view[
            df_view["Data_Inicio"].notna() &
            df_view["Data_Fim"].notna() &
            (df_view["Data_Inicio"].dt.date <= end_month) &
            (df_view["Data_Fim"].dt.date >= start_month)
        ]
        this_month_count = len(this_month)
    else:
        this_month_count = 0

    return total, next_date, this_month_count





# -------------------------------------------------
# TORNEIOS: STORAGE (Google Sheets + Dropbox)
# -------------------------------------------------
from modules.storage import read_torneios, read_sheet, save_inscricao, normalize_phone

# -------------------------------------------------
# TOP-LEVEL NAV (Tabs): Calendário / Pontos / Rankings
# ✅ Rankings fica imediatamente ao lado de Pontos
# -------------------------------------------------
_inject_tab_restorer_js()  # restores selected tab after reruns
tab_cal, tab_tour, tab_pts, tab_rank = st.tabs(["📅 Calendário", "🎾 Torneios", "🧮 Pontos", "🏆 Rankings"])

# -------------------------------------------------
# CALENDÁRIO TAB
# -------------------------------------------------
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

# -------------------------------------------------
# -------------------------------------------------
# TORNEIOS TAB (cards + inscrição + organizador)
# -------------------------------------------------
# -------------------------------------------------
# TORNEIOS TAB (cards + inscrição + organizador)
# -------------------------------------------------
with tab_tour:
    render_tournaments(is_mobile=bool(st.session_state.get("is_mobile", False)))


with tab_pts:
    render_points()

# -------------------------------------------------
# RANKINGS TAB (link)
# -------------------------------------------------
with tab_rank:
    render_rankings()

