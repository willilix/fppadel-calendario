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
st.set_page_config(page_title="Calendário FPPadel", page_icon="🎾", layout="wide")

# Apple Sports UI (CSS)
st.markdown("""
<style>
/* Container */
.block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1120px; }
header { visibility: hidden; height: 0px; }

/* Typography */
h1, h2, h3 { letter-spacing: -0.02em; }
a, a:visited { color: #0A84FF !important; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Top bar */
.topbar {
  background: rgba(255,255,255,0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(17,17,17,0.08);
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 12px;
  box-shadow: 0 10px 30px rgba(17,17,17,0.06);
}
.top-title { font-weight: 750; font-size: 1.35rem; margin: 0; }
.top-sub { color: rgba(17,17,17,0.62); font-size: 0.95rem; margin-top: 4px; }

/* Pills */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 999px;
  border: 1px solid rgba(17,17,17,0.10);
  background: rgba(17,17,17,0.03);
  font-size: 0.78rem;
  color: rgba(17,17,17,0.80);
}

/* Metric cards */
.metric {
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid rgba(17,17,17,0.06);
  box-shadow: 0 10px 30px rgba(17,17,17,0.05);
  padding: 14px 14px;
}
.metric .label { color: rgba(17,17,17,0.62); font-size: 0.82rem; }
.metric .value { font-weight: 760; font-size: 1.15rem; margin-top: 4px; }
.metric .hint { color: rgba(17,17,17,0.55); font-size: 0.80rem; margin-top: 3px; }

/* Wallet-like cards (mobile) */
.card {
  border-radius: 22px;
  background: #FFFFFF;
  border: 1px solid rgba(17,17,17,0.06);
  box-shadow: 0 12px 38px rgba(17,17,17,0.07);
  padding: 16px 16px;
  margin-bottom: 12px;
}
.card .title { font-weight: 760; font-size: 1.03rem; }
.card .row { margin-top: 8px; color: rgba(17,17,17,0.72); font-size: 0.93rem; line-height: 1.32; }
.card .actions { margin-top: 12px; }

/* Inputs / buttons */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div { border-radius: 14px !important; }

.stButton button {
  border-radius: 14px !important;
  padding: 0.55rem 0.9rem !important;
}

/* Dataframe (desktop) */
[data-testid="stDataFrame"] {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(17,17,17,0.08);
  box-shadow: 0 10px 30px rgba(17,17,17,0.04);
}

/* Tabs spacing */
.stTabs [data-baseweb="tab-list"] {
  gap: 8px;
}
.stTabs [data-baseweb="tab"] {
  border-radius: 999px;
  border: 1px solid rgba(17,17,17,0.10);
  background: rgba(17,17,17,0.03);
  padding: 8px 14px;
}
.stTabs [aria-selected="true"] {
  background: rgba(10,132,255,0.12);
  border-color: rgba(10,132,255,0.35);
}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# CONSTANTS
# -------------------------------------------------
HOME_URL = "https://fppadel.pt/"
WP_MEDIA_SEARCH = "https://fppadel.pt/wp-json/wp/v2/media"

MONTHS = [
    "JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO",
    "JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"
]
MONTH_TO_NUM = {m.title(): i for i, m in enumerate(MONTHS, start=1)}

# -------------------------------------------------
# MOBILE DETECTION (best-effort)
# -------------------------------------------------
if "is_mobile" not in st.session_state:
    st.session_state["is_mobile"] = False

components.html("""
<script>
  try {
    const isMobile = window.matchMedia("(max-width: 768px)").matches;
    window.parent.postMessage(
      { type: "streamlit:setSessionState", key: "is_mobile", value: !!isMobile },
      "*"
    );
  } catch(e) {}
</script>
""", height=0)

is_mobile = bool(st.session_state.get("is_mobile", False))

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def month_sort_key(m: str) -> int:
    try:
        return MONTHS.index(m.upper())
    except ValueError:
        return 999

def _pick_highest_version(urls: list[str]) -> str:
    """Pick the highest '-<n>.pdf' suffix if present; otherwise fallback to alpha."""
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
    if end_day < start_day:  # crosses month
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
    if "gold" in c or "50.000" in c: return "🥇"
    if "silver" in c: return "🥈"
    if "bronze" in c: return "🥉"
    if "continental" in c or "promises" in c: return "🌍"
    if "a definir" in c: return "❓"
    if "10.000" in c: return "🔵"
    if "5.000" in c: return "🟢"
    if "2.000" in c: return "⚪"
    return ""

# -------------------------------------------------
# DISCOVER LATEST PDF
# -------------------------------------------------
@st.cache_data(ttl=900)
def find_latest_calendar_pdf_url() -> str:
    # 1) Home scrape (prefer “saber mais”)
    try:
        html = requests.get(HOME_URL, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = (a.get_text() or "").strip().lower()
            if "saber mais" in text and href.lower().endswith(".pdf") and "calend" in href.lower():
                candidates.append(urljoin(HOME_URL, href))

        # fallback: any calendar pdf
        if not candidates:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.lower().endswith(".pdf") and "calend" in href.lower():
                    candidates.append(urljoin(HOME_URL, href))

        if candidates:
            return _pick_highest_version(candidates)
    except Exception:
        pass

    # 2) WordPress media search fallback
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

@st.cache_data(ttl=900)
def download_pdf_bytes(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, timeout=30)
    r.raise_for_status()
    return r.content

# -------------------------------------------------
# PARSER (robusto: LOCAL/ORGANIZAÇÃO por coordenadas)
# -------------------------------------------------
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

            # detect column x for LOCAL and ORGANIZAÇÃO from header on this page
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

                # month detection
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

                # DIV
                div_idx = None
                for i, t in enumerate(tokens):
                    if t in ("ABS", "JOV"):
                        div_idx = i
                        break
                if div_idx is None:
                    continue
                div = tokens[div_idx]

                # day text (before tipo)
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

                # class
                class_end = euro_idx if euro_idx is not None else len(rest)
                classe = ""
                class_start = None

                # "A definir"
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

                # categories
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

                # LOCAL & ORGANIZAÇÃO from x columns
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
                    # fallback (rare)
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

# -------------------------------------------------
# BUILD DISPLAY FIELDS
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

def compute_metrics(df_view: pd.DataFrame):
    total = len(df_view)

    today = dt.date.today()
    next_date = None
    if "Data_Inicio" in df_view.columns and not df_view.empty:
        future = df_view[df_view["Data_Inicio"].notna() & (df_view["Data_Inicio"] >= today)].copy()
        if not future.empty:
            future = future.sort_values(["Data_Inicio", "DIV", "Actividade"])
            next_date = future.iloc[0]["Data_Inicio"]

    # this month count (by overlap)
    start_month = dt.date(today.year, today.month, 1)
    if today.month == 12:
        end_month = dt.date(today.year, 12, 31)
    else:
        end_month = dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)

    this_month = df_view[
        (df_view["Data_Inicio"].notna()) &
        (df_view["Data_Fim"].notna()) &
        (df_view["Data_Inicio"] <= end_month) &
        (df_view["Data_Fim"] >= start_month)
    ]
    return total, next_date, len(this_month)

# -------------------------------------------------
# UI TOP BAR
# -------------------------------------------------
left, right = st.columns([1, 1])
with right:
    if st.button("⟲ Actualizar", help="Ignora cache e volta a detectar o PDF mais recente"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("A detectar o PDF mais recente e a extrair dados…"):
    pdf_url = find_latest_calendar_pdf_url()
    pdf_name = os.path.basename(urlparse(pdf_url).path)
    year = infer_year_from_pdf_url(pdf_url)
    pdf_bytes = download_pdf_bytes(pdf_url)
    df = parse_calendar_pdf(pdf_bytes, year=year)

prev = st.session_state.get("last_pdf_name")
st.session_state["last_pdf_name"] = pdf_name
new_badge = " • 🟢 nova versão" if (prev and prev != pdf_name) else ""

st.markdown(f"""
<div class="topbar">
  <div class="top-title">Calendário FPPadel</div>
  <div class="top-sub">ABS e JOV • actualizado automaticamente • Maps{new_badge}</div>
  <div style="display:flex; gap:10px; margin-top:10px; flex-wrap:wrap;">
    <span class="pill">PDF: {pdf_name}</span>
    <span class="pill">Ano: {year}</span>
  </div>
</div>
""", unsafe_allow_html=True)

st.link_button("Abrir PDF original", pdf_url)

if df.empty:
    st.error("Não consegui extrair linhas do PDF (o formato pode ter mudado).")
    st.stop()

# Display fields
df["Local"] = df.apply(build_local_dash_org, axis=1)
df["Destaque"] = df["Classe"].apply(class_badge)
df["Mapa"] = df["Local"].apply(lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}")

# -------------------------------------------------
# TABS (ABS / JOV / Ambos)
# -------------------------------------------------
tab_abs, tab_jov, tab_all = st.tabs(["ABS", "JOV", "ABS + JOV"])

def render_view(div_value: str | None):
    base = df.copy()
    if div_value in ("ABS", "JOV"):
        base = base[base["DIV"] == div_value].copy()

    # Filters (mobile: expander; desktop: row)
    if is_mobile:
        with st.expander("Filtros", expanded=False):
            mes_opts = sorted(base["Mes"].unique(), key=month_sort_key)
            mes_sel = st.selectbox("Mês", ["(Todos)"] + mes_opts, key=f"mes_{div_value}")
            classes = sorted([c for c in base["Classe"].unique() if isinstance(c, str) and c.strip()])
            classe_sel = st.multiselect("Classe", classes, default=[], key=f"classe_{div_value}")
            quick = st.selectbox("Datas", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"], key=f"quick_{div_value}")
            search = st.text_input("Pesquisa", key=f"search_{div_value}")
    else:
        c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
        with c1:
            mes_opts = sorted(base["Mes"].unique(), key=month_sort_key)
            mes_sel = st.selectbox("Mês", ["(Todos)"] + mes_opts, key=f"mes_{div_value}")
        with c2:
            classes = sorted([c for c in base["Classe"].unique() if isinstance(c, str) and c.strip()])
            classe_sel = st.multiselect("Classe", classes, default=[], key=f"classe_{div_value}")
        with c3:
            quick = st.selectbox("Datas", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"], key=f"quick_{div_value}")
        with c4:
            search = st.text_input("Pesquisa", placeholder="Lisboa, FIP, S14, Madeira…", key=f"search_{div_value}")

    view = base.copy()

    # Apply filters
    if mes_sel != "(Todos)":
        view = view[view["Mes"] == mes_sel]

    if classe_sel:
        view = view[view["Classe"].isin(classe_sel)]

    today = dt.date.today()
    if quick != "(Nenhum)":
        if quick == "Este mês":
            start = dt.date(today.year, today.month, 1)
            end = (dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)) if today.month != 12 else dt.date(today.year, 12, 31)
        elif quick == "Próximos 7 dias":
            start = today
            end = today + dt.timedelta(days=7)
        else:
            start = today
            end = today + dt.timedelta(days=30)

        view = view[
            (view["Data_Inicio"].notna()) &
            (view["Data_Fim"].notna()) &
            (view["Data_Inicio"] <= end) &
            (view["Data_Fim"] >= start)
        ]

    if search.strip():
        q = search.strip().lower()
        cols = ["Data (mês + dia)", "DIV", "Actividade", "Categorias", "Classe", "Local", "Mes"]
        mask = False
        for col in cols:
            mask = mask | view[col].astype(str).str.lower().str.contains(q, na=False)
        view = view[mask]

    # Metrics (Apple style)
    total, next_date, this_month_count = compute_metrics(view)
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""
        <div class="metric">
          <div class="label">Eventos</div>
          <div class="value">{total}</div>
          <div class="hint">na selecção actual</div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        nxt = next_date.strftime("%d/%m") if next_date else "—"
        st.markdown(f"""
        <div class="metric">
          <div class="label">Próximo</div>
          <div class="value">{nxt}</div>
          <div class="hint">data de início</div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="metric">
          <div class="label">Este mês</div>
          <div class="value">{this_month_count}</div>
          <div class="hint">eventos a decorrer</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Actividades")

    out = view[[
        "Data (mês + dia)",
        "DIV",
        "Actividade",
        "Categorias",
        "Classe",
        "Local",
        "Destaque",
        "Mapa",
    ]].copy()

    # Output: wallet cards on mobile, clean table on desktop
    if is_mobile:
        for _, row in out.iterrows():
            badge_div = row["DIV"]
            badge_rank = normalize_text(row["Destaque"])
            pills = f'<span class="pill">{badge_div}</span>'
            if badge_rank:
                pills += f' <span class="pill">{badge_rank}</span>'

            st.markdown(f"""
            <div class="card">
              <div class="title">{row['Actividade']}</div>
              <div class="row">{row['Data (mês + dia)']} &nbsp; {pills}</div>
              <div class="row"><b>Categorias:</b> {row['Categorias']}</div>
              <div class="row"><b>Classe:</b> {row['Classe']}</div>
              <div class="row"><b>Local:</b> {row['Local']}</div>
              <div class="actions">
                <a href="{row['Mapa']}" target="_blank">Abrir no Maps →</a>
              </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.dataframe(
            out,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Mapa": st.column_config.LinkColumn("Mapa", display_text="Maps"),
                "Destaque": st.column_config.TextColumn("Destaque"),
            }
        )

    st.download_button(
        "Download CSV (filtrado)",
        data=out.drop(columns=["Mapa"]).to_csv(index=False).encode("utf-8"),
        file_name=f"calendario_fppadel_{pdf_name.replace('.pdf','')}.csv",
        mime="text/csv"
    )

with tab_abs:
    render_view("ABS")

with tab_jov:
    render_view("JOV")

with tab_all:
    render_view(None)
