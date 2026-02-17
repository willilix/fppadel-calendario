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
import uuid
import io

# 👇 points calculator sub-app
from points_calculator import render_points_calculator

# 🧪 STAGING badge automático

IS_STAGING = os.path.exists("STAGING")

if IS_STAGING:
    st.markdown(
        """
        <style>
        .staging-badge {
            position: fixed;
            top: 70px;
            right: 20px;
            background: #ff4b4b;
            color: white;
            padding: 8px 14px;
            border-radius: 10px;
            font-weight: 600;
            z-index: 100000;
            box-shadow: 0 6px 16px rgba(0,0,0,0.25);
        }
        </style>
        <div class="staging-badge">🧪 STAGING</div>
        """,
        unsafe_allow_html=True
    )

def ga4_track_pageview():
    # evita enviar 20 eventos por causa dos reruns do Streamlit
    if st.session_state.get("_ga_sent"):
        return
    st.session_state["_ga_sent"] = True

    measurement_id = st.secrets.get("GA_MEASUREMENT_ID", "")
    api_secret = st.secrets.get("GA_API_SECRET", "")
    if not measurement_id or not api_secret:
        return

    # client_id simples por sessão (não é PII)
    client_id = st.session_state.get("_ga_client_id")
    if not client_id:
        client_id = f"{uuid.uuid4()}.{uuid.uuid4()}"
        st.session_state["_ga_client_id"] = client_id

    url = f"https://www.google-analytics.com/mp/collect?measurement_id={measurement_id}&api_secret={api_secret}"

    payload = {
        "client_id": client_id,
        "events": [
            {
                "name": "page_view",
                "params": {
                    "page_title": "FPPadel Calendário",
                    "page_location": "streamlit_app",
                },
            }
        ],
    }

    try:
        requests.post(url, json=payload, timeout=3)
    except Exception:
        pass


# ---------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA (SÓ UMA VEZ)
# ---------------------------------------------------
st.set_page_config(
    page_title="FPPadel Calendário",
    page_icon="icon.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

import os, base64
import streamlit as st
import streamlit.components.v1 as components

def set_ios_home_icon(path="icon.png"):
    if not os.path.exists(path):
        return

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    # JS injeta o link no <head>
    components.html(
        f"""
        <script>
          (function() {{
            const href = "data:image/png;base64,{b64}";

            // apple-touch-icon
            let link = document.querySelector("link[rel='apple-touch-icon']");
            if (!link) {{
              link = document.createElement("link");
              link.rel = "apple-touch-icon";
              document.head.appendChild(link);
            }}
            link.href = href;

            // favicon (opcional, ajuda nalguns casos)
            let icon = document.querySelector("link[rel='icon']");
            if (!icon) {{
              icon = document.createElement("link");
              icon.rel = "icon";
              document.head.appendChild(icon);
            }}
            icon.href = href;

            // PWA-ish (opcional)
            let meta = document.querySelector("meta[name='apple-mobile-web-app-capable']");
            if (!meta) {{
              meta = document.createElement("meta");
              meta.name = "apple-mobile-web-app-capable";
              meta.content = "yes";
              document.head.appendChild(meta);
            }}
          }})();
        </script>
        """,
        height=0,
        width=0,
    )

set_ios_home_icon("icon.png")



import os
import streamlit as st

IS_STAGING = os.path.exists("STAGING")

if IS_STAGING:
    st.markdown(
        """
        <style>
        .staging-badge {
            position: fixed;
            top: 70px;
            right: 20px;
            background: #ff4b4b;
            color: white;
            padding: 8px 14px;
            border-radius: 10px;
            font-weight: 600;
            z-index: 100000;
            box-shadow: 0 6px 16px rgba(0,0,0,0.25);
        }
        </style>
        <div class="staging-badge">🧪 STAGING</div>
        """,
        unsafe_allow_html=True
    )


ga4_track_pageview()

# ---------------------------------------------------
# GOOGLE ANALYTICS (GA4)
# ---------------------------------------------------
components.html(
    """
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-RLL0HMMSVZ"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());

      // Força configuração com domínio correto
      gtag('config', 'G-RLL0HMMSVZ', {
        page_path: window.location.pathname,
        page_title: document.title,
        page_location: window.location.href,
        send_page_view: true
      });
    </script>
    """,
    height=0,
)

def ga_event(name: str, params: dict | None = None):
    """Envia um evento GA4 (client-side)."""
    params = params or {}
    js_params = str(params).replace("'", '"')  # JSON simples
    components.html(
        f"""
        <script>
          (function() {{
            const params = {js_params};
            // tenta no próprio frame
            if (typeof gtag === 'function') {{
              gtag('event', '{name}', params);
              return;
            }}
            // tenta no parent (caso o gtag esteja no topo)
            if (window.parent && typeof window.parent.gtag === 'function') {{
              window.parent.gtag('event', '{name}', params);
              return;
            }}
          }})();
        </script>
        """,
        height=0,
    )


def ga_install_tab_listeners_once():
    """Instala listeners JS para track de tabs (só 1x por sessão)."""
    if st.session_state.get("_ga_tabs_listeners"):
        return
    st.session_state["_ga_tabs_listeners"] = True

    components.html(
        """
        <script>
          (function() {
            function send(name, params){
              params = params || {};
              if (typeof gtag === 'function') { gtag('event', name, params); return; }
              if (window.parent && typeof window.parent.gtag === 'function') { window.parent.gtag('event', name, params); return; }
            }

            function bindTabs(){
              const tabs = document.querySelectorAll('button[role="tab"]');
              tabs.forEach((btn) => {
                if (btn.dataset.gaBound === "1") return;
                btn.dataset.gaBound = "1";
                btn.addEventListener('click', () => {
                  const tabName = (btn.innerText || "").trim();
                  if (tabName) send('tab_change', { tab_name: tabName });
                }, { passive: true });
              });
            }

            // tenta já
            bindTabs();

            // e volta a tentar quando o Streamlit re-renderiza
            const obs = new MutationObserver(() => bindTabs());
            obs.observe(document.body, { childList: true, subtree: true });
          })();
        </script>
        """,
        height=0,
    )


# ---------------------------------------------------
# APPLE PREMIUM DARK UI
# ---------------------------------------------------
st.markdown("""
<style>

/* Layout base */
.block-container {
    padding-top: 1.1rem;
    padding-bottom: 3rem;
    max-width: 1120px;
}

header { visibility: hidden; }

/* Fundo geral premium */
.stApp {
    background:
        radial-gradient(1200px 600px at 50% -10%, rgba(10,132,255,0.18), rgba(0,0,0,0) 55%),
        linear-gradient(180deg, #0B0B10 0%, #07070A 100%);
    color: rgba(237,237,243,0.96);
}

/* Links */
a, a:visited {
    color: #0A84FF !important;
    text-decoration: none;
}
a:hover { text-decoration: underline; }

/* Topbar glass */
.topbar {
    background: rgba(18,18,26,0.68);
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 16px;
    margin-bottom: 18px;
    box-shadow: 0 18px 60px rgba(0,0,0,0.55);
}

.top-title {
    font-weight: 800;
    font-size: 1.4rem;
    margin: 0;
}

.top-sub {
    color: rgba(237,237,243,0.6);
    font-size: 0.95rem;
}

/* Pills */
.pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.05);
    font-size: 0.78rem;
}

/* Metric cards */
.metric {
    border-radius: 20px;
    background: rgba(18,18,26,0.75);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 18px 60px rgba(0,0,0,0.55);
    padding: 16px;
    transition: all 0.25s ease;
}

.metric:hover {
    transform: translateY(-2px);
    box-shadow: 0 24px 70px rgba(0,0,0,0.65);
}

.metric .label {
    color: rgba(237,237,243,0.6);
    font-size: 0.82rem;
}

.metric .value {
    font-weight: 800;
    font-size: 1.2rem;
    margin-top: 6px;
}

.metric .hint {
    color: rgba(237,237,243,0.5);
    font-size: 0.8rem;
}

/* Cards mobile style */
.card {
    border-radius: 24px;
    background: rgba(18,18,26,0.75);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 18px 60px rgba(0,0,0,0.55);
    padding: 18px;
    margin-bottom: 14px;
    transition: all 0.25s ease;
}

.card:hover {
    transform: translateY(-2px);
    box-shadow: 0 24px 70px rgba(0,0,0,0.65);
}

.card .title {
    font-weight: 800;
    font-size: 1.05rem;
}

.card .row {
    margin-top: 8px;
    font-size: 0.92rem;
    color: rgba(237,237,243,0.75);
}

/* Inputs */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div {
    border-radius: 16px !important;
}

/* Botões */
.stButton button {
    border-radius: 16px !important;
    padding: 0.55rem 1rem !important;
    font-weight: 600;
}

/* Tabs estilo Apple */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.05);
    padding: 8px 16px;
    color: rgba(237,237,243,0.75);
}

.stTabs [aria-selected="true"] {
    background: rgba(10,132,255,0.18);
    border-color: rgba(10,132,255,0.45);
    color: white;
}

/* Dataframe */
[data-testid="stDataFrame"] {
    border-radius: 20px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.1);
    box-shadow: 0 18px 60px rgba(0,0,0,0.5);
}

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------
# A PARTIR DAQUI MANTÉM O TEU CÓDIGO ORIGINAL
# (lógica calendário, PDF parsing, filtros, etc.)
# ---------------------------------------------------

# ⚠️ NÃO ALTERAR NADA ABAIXO DESTE PONTO
# Cola aqui exatamente o resto do teu código actual


# -------------------------------------------------
# LOGO + TEXTO (centrado + premium Apple)
# -------------------------------------------------

st.markdown("""
<style>
.logo-wrap{
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    text-align:center;
    gap:14px;
    margin: 10px 0 30px 0;
}

.logo-img{
    height:380px;   /* ← altera aqui se quiseres maior/menor */
    width:auto;
    object-fit:contain;

    /* Apple-style shadow */
    filter: drop-shadow(0 20px 40px rgba(0,0,0,0.45))
            drop-shadow(0 6px 12px rgba(0,0,0,0.35));

    /* Micro fade + lift */
    animation: fadeUp 0.65s ease-out both;
}

.logo-text{
    font-size:1rem;
    font-weight:500;
    opacity:0.85;
    animation: fadeIn 0.9s ease-out both;
}

@keyframes fadeUp{
    from { opacity:0; transform: translateY(10px) scale(0.98); }
    to   { opacity:1; transform: translateY(0) scale(1); }
}

@keyframes fadeIn{
    from { opacity:0; }
    to   { opacity:0.85; }
}
</style>
""", unsafe_allow_html=True)


logo_path = "armadura.png"
if os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    st.markdown(f"""
    <div class="logo-wrap">
      <img class="logo-img" src="data:image/png;base64,{b64}" alt="armadura" />
      <div class="logo-text">
        App oficial dos 6 zeritas - Powered by Grupo do 60
      </div>
    </div>
    """, unsafe_allow_html=True)

else:
    st.markdown("""
    <div class="logo-wrap">
      <div class="logo-text">
        App oficial dos 6 zeritas - Powered by Grupo do 60
      </div>
    </div>
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



# =================================================
# TORNEIOS: STORAGE HELPERS (Google Sheets + Dropbox)
# =================================================
# Dados: Google Sheets (Service Account)
# Fotos: Dropbox (Full Dropbox) em pasta específica
#
# Secrets necessários:
#   SHEET_ID
#   [GCP_SERVICE_ACCOUNT]
#   DROPBOX_TOKEN
#
# Dependências:
#   gspread
#   google-auth
#   dropbox
# =================================================

DROPBOX_BASE_PATH = "/Torneios/Fotos"  # podes mudar no código (ou tornar secret se quiseres)

def has_google_secrets() -> bool:
    return all(k in st.secrets for k in ["GCP_SERVICE_ACCOUNT", "SHEET_ID"])

def has_dropbox_token() -> bool:
    return bool(st.secrets.get("DROPBOX_TOKEN", "").strip())

def normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    phone = re.sub(r"[^\d+]", "", phone)
    return phone

def safe_slug(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
    return text[:60] if text else "user"

import gspread
from google.oauth2.service_account import Credentials

@st.cache_resource
def google_spreadsheet():
    sa_info = dict(st.secrets["GCP_SERVICE_ACCOUNT"])

    pk = sa_info.get("private_key", "")
    if "\\n" in pk:
        sa_info["private_key"] = pk.replace("\\n", "\n")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)

    gc = gspread.authorize(creds)
    return gc.open_by_key(st.secrets["SHEET_ID"])


def google_ws(name: str):
    """Abre uma worksheet pelo nome (ex: 'inscricoes', 'Torneios')."""
    return google_spreadsheet().worksheet(name)


def google_sheet():
    # Mantém compatibilidade com inscrições
    return google_ws("inscricoes")

def ensure_headers(ws):
    wanted = ["torneio_id","torneio_nome","timestamp","nome","telefone","foto_url","storage"]
    headers = ws.row_values(1)
    if headers != wanted:
        ws.clear()
        ws.append_row(wanted)
    return wanted

def append_to_sheet(row: dict):
    ws = google_sheet()
    ensure_headers(ws)
    ws.append_row([
        row.get("torneio_id",""),
        row.get("torneio_nome",""),
        row.get("timestamp",""),
        row.get("nome",""),
        row.get("telefone",""),
        row.get("foto_url",""),
        row.get("storage","dropbox"),
    ])

def read_sheet() -> pd.DataFrame:
    ws = google_sheet()
    values = ws.get_all_values()
    if len(values) <= 1:
        cols = values[0] if values else ["torneio_id","torneio_nome","timestamp","nome","telefone","foto_url","storage"]
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(values[1:], columns=values[0])


def read_torneios() -> list[dict]:
    """Lê a aba 'Torneios' da Google Sheet e devolve lista de torneios ativos."""
    import gspread

    try:
        ws = google_ws("Torneios")
    except gspread.exceptions.WorksheetNotFound:
        st.error("A aba 'Torneios' não existe na Google Sheet.")
        return []

    values = ws.get_all_values()
    if len(values) <= 1:
        return []

    headers = values[0]
    rows = values[1:]

    torneios: list[dict] = []
    for row in rows:
        data = dict(zip(headers, row))

        if str(data.get("ativo", "")).upper() != "TRUE":
            continue

        # vagas pode vir vazio
        try:
            vagas = int(data.get("vagas") or 0)
        except Exception:
            vagas = 0

        torneios.append({
            "id": data.get("id"),
            "nome": data.get("nome"),
            "data": data.get("data"),
            "local": data.get("local"),
            "descricao": data.get("descricao", ""),
            "img": data.get("imagem_url"),
            "vagas": vagas,
        })

    return torneios



def upload_photo_to_dropbox(file_bytes: bytes, torneio_id: str, filename: str) -> str:
    """Upload para Dropbox (Full Dropbox) e devolve URL direto (raw=1)."""
    import dropbox
    from dropbox.files import WriteMode
    from dropbox.sharing import SharedLinkSettings
    from dropbox.exceptions import ApiError

    token = st.secrets["DROPBOX_TOKEN"].strip()
    dbx = dropbox.Dropbox(token)

    base = DROPBOX_BASE_PATH.rstrip("/")
    folder_path = f"{base}/{torneio_id}"

    # Garante que as pastas existem (ignora se já existirem)
    try:
        dbx.files_create_folder_v2(base)
    except Exception:
        pass
    try:
        dbx.files_create_folder_v2(folder_path)
    except Exception:
        pass

    dropbox_path = f"{folder_path}/{filename}"

    dbx.files_upload(file_bytes, dropbox_path, mode=WriteMode.overwrite, mute=True)

    # criar link (se já existir, reaproveita)
    try:
        link_meta = dbx.sharing_create_shared_link_with_settings(
            dropbox_path,
            settings=SharedLinkSettings()
        )
        url = link_meta.url
    except ApiError as e:
        if getattr(e, "error", None) and e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=dropbox_path, direct_only=True).links
            url = links[0].url
        else:
            raise

    return url.replace("?dl=0", "?raw=1")

def save_inscricao(torneio: dict, nome: str, telefone: str, foto):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    telefone_norm = normalize_phone(telefone)

    file_bytes = foto.getvalue()
    ext = (foto.name.split(".")[-1] if foto and foto.name and "." in foto.name else "jpg").lower()
    filename = f"{torneio['id']}_{int(dt.datetime.now().timestamp())}_{safe_slug(nome)}.{ext}"

    foto_url = upload_photo_to_dropbox(file_bytes, torneio["id"], filename)

    row = {
        "torneio_id": torneio["id"],
        "torneio_nome": torneio["nome"],
        "timestamp": ts,
        "nome": nome.strip(),
        "telefone": telefone_norm,
        "foto_url": foto_url,
        "storage": "dropbox",
    }
    append_to_sheet(row)

# -------------------------------------------------
# TOP-LEVEL NAV (Tabs): Calendário / Pontos / Rankings
# ✅ Rankings fica imediatamente ao lado de Pontos
# -------------------------------------------------
tab_cal, tab_tour, tab_pts, tab_rank = st.tabs(["📅 Calendário", "🎾 Torneios", "🧮 Pontos", "🏆 Rankings"])

# -------------------------------------------------
# CALENDÁRIO TAB
# -------------------------------------------------
with tab_cal:
    left, right = st.columns([1, 1])
    with right:
        if st.button("⟲ Actualizar", help="Ignora cache e volta a detectar o PDF mais recente"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("A detectar o PDF mais recente e a extrair dados…"):
        try:
            pdf_url = find_latest_calendar_pdf_url()
            pdf_name = os.path.basename(urlparse(pdf_url).path)
            year = infer_year_from_pdf_url(pdf_url)
            pdf_bytes = download_pdf_bytes(pdf_url)

            df = parse_calendar_pdf(pdf_bytes, year=year)
            df = normalize_and_dedupe(df)

            # guarda último bom (para resiliência quando o site/PDF falha)
            st.session_state["df_ok"] = df
            st.session_state["pdf_url_ok"] = pdf_url
            st.session_state["pdf_name_ok"] = pdf_name
            st.session_state["year_ok"] = year
        except Exception:
            df = st.session_state.get("df_ok")
            pdf_url = st.session_state.get("pdf_url_ok", "")
            pdf_name = st.session_state.get("pdf_name_ok", "—")
            year = st.session_state.get("year_ok", dt.date.today().year)

            st.warning("Não consegui atualizar agora — a mostrar a última versão disponível.")
            if df is None or (hasattr(df, "empty") and df.empty):
                st.error("Ainda não há dados em cache. Tenta novamente daqui a pouco.")
                st.stop()

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

    df["Local"] = df.apply(build_local_dash_org, axis=1)
    df["Local"] = df["Local"].astype("string").fillna("").str.replace(r"\s+", " ", regex=True).str.strip().replace({"": pd.NA})
    df["Mapa"] = df["Local"].apply(lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}")

    tab_abs, tab_jov, tab_all = st.tabs(["ABS", "JOV", "ABS + JOV"])

    def render_view(div_value: str | None):
        tab_key = (div_value or "ALL")

        base = df.copy()
        if div_value in ("ABS", "JOV"):
            base = base[base["DIV"] == div_value].copy()

        # Filters (em form para não recalcular a cada clique)
        if is_mobile:
            with st.expander("Filtros", expanded=False):
                with st.form(key=f"filtros_form_{tab_key}"):
                    mes_opts = sorted(base["Mes"].unique(), key=month_sort_key)
                    mes_sel = st.selectbox("Mês", ["(Todos)"] + mes_opts, key=f"mes_{tab_key}")
                    classes = sorted([c for c in base["Classe"].unique() if isinstance(c, str) and c.strip()])
                    classe_sel = st.multiselect("Classe", classes, default=[], key=f"classe_{tab_key}")
                    quick = st.selectbox("Datas", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"], key=f"quick_{tab_key}")
                    search = st.text_input("Pesquisa", key=f"search_{tab_key}")
                    st.form_submit_button("Aplicar")
        else:
            with st.form(key=f"filtros_form_{tab_key}"):
                c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                with c1:
                    mes_opts = sorted(base["Mes"].unique(), key=month_sort_key)
                    mes_sel = st.selectbox("Mês", ["(Todos)"] + mes_opts, key=f"mes_{tab_key}")
                with c2:
                    classes = sorted([c for c in base["Classe"].unique() if isinstance(c, str) and c.strip()])
                    classe_sel = st.multiselect("Classe", classes, default=[], key=f"classe_{tab_key}")
                with c3:
                    quick = st.selectbox("Datas", ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"], key=f"quick_{tab_key}")
                with c4:
                    search = st.text_input("Pesquisa", placeholder="Lisboa, FIP, S14, Madeira…", key=f"search_{tab_key}")
                st.form_submit_button("Aplicar")

        view = base.copy()

        # garantir datas como datetime (para filtros funcionarem)
        view["Data_Inicio"] = pd.to_datetime(view["Data_Inicio"], errors="coerce")
        view["Data_Fim"] = pd.to_datetime(view["Data_Fim"], errors="coerce")

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
                (view["Data_Inicio"].dt.date <= end) &
                (view["Data_Fim"].dt.date >= start)
            ]

        if search.strip():
            q = search.strip().lower()
            cols = ["Data (mês + dia)", "DIV", "Categorias", "Classe", "Local", "Mes"]
            mask = False
            for col in cols:
                mask = mask | view[col].astype(str).str.lower().str.contains(q, na=False)
            view = view[mask]

        # Metrics: total respeita filtros; "Este mês" e "Próximo" NÃO dependem do mês escolhido
        total = len(view)

        metrics_df = base.copy()  # <- importante: base (tab), não view (filtrado por mês)

        metrics_df["Data_Inicio"] = pd.to_datetime(metrics_df["Data_Inicio"], errors="coerce")
        metrics_df["Data_Fim"] = pd.to_datetime(metrics_df["Data_Fim"], errors="coerce")

        today = dt.date.today()

        # Próximo evento (no separador, independentemente do mês escolhido)
        next_date = None
        future = metrics_df[
            metrics_df["Data_Inicio"].notna() &
            (metrics_df["Data_Inicio"].dt.date >= today)
        ]
        if not future.empty:
            sort_cols = [c for c in ["Data_Inicio", "DIV", "Categorias"] if c in future.columns]
            future = future.sort_values(sort_cols if sort_cols else ["Data_Inicio"])
            next_date = future.iloc[0]["Data_Inicio"]

        # Eventos a decorrer este mês (mês actual, no separador, independentemente do mês escolhido)
        start_month = dt.date(today.year, today.month, 1)
        end_month = (dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)) if today.month != 12 else dt.date(today.year, 12, 31)

        this_month = metrics_df[
            metrics_df["Data_Inicio"].notna() &
            metrics_df["Data_Fim"].notna() &
            (metrics_df["Data_Inicio"].dt.date <= end_month) &
            (metrics_df["Data_Fim"].dt.date >= start_month)
        ]
        this_month_count = len(this_month)

                # Render Metrics (caixas)
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

        # (sem Actividade / sem Destaque)
        out = view[[
            "Data (mês + dia)",
            "DIV",
            "Categorias",
            "Classe",
            "Local",
            "Mapa",
        ]].copy()

        if is_mobile:
            for _, row in out.iterrows():
                title = row.get("Categorias") or row.get("Classe") or row.get("Local") or "Evento"
                pills = f'<span class="pill">{row["DIV"]}</span>'

                st.markdown(f"""
                <div class="card">
                  <div class="title">{title}</div>
                  <div class="row">{row['Data (mês + dia)']} &nbsp; {pills}</div>
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
                key=f"df_{tab_key}",
                column_config={
                    "Mapa": st.column_config.LinkColumn("Mapa", display_text="Maps"),
                }
            )

        st.download_button(
            "Download CSV (filtrado)",
            data=out.drop(columns=["Mapa"]).to_csv(index=False).encode("utf-8"),
            file_name=f"calendario_fppadel_{tab_key.lower()}_{pdf_name.replace('.pdf','')}.csv",
            mime="text/csv",
            key=f"dl_{tab_key}"
        )

    with tab_abs:
        render_view("ABS")
    with tab_jov:
        render_view("JOV")
    with tab_all:
        render_view(None)
# -------------------------------------------------
# -------------------------------------------------
# TORNEIOS TAB (cards + inscrição + organizador)
# -------------------------------------------------
# -------------------------------------------------
# TORNEIOS TAB (cards + inscrição + organizador)
# -------------------------------------------------
with tab_tour:
    st.markdown("""
    <div class="topbar">
      <div class="top-title">Torneios</div>
      <div class="top-sub">Inscrições dentro da app • com foto • área do organizador</div>
    </div>
    """, unsafe_allow_html=True)

    # -----------------
    # Dados (Google Sheet)
    # -----------------
    TORNEIOS = read_torneios()

    # --------
    # Estado
    # --------
    if "torneio_sel" not in st.session_state:
        st.session_state.torneio_sel = (TORNEIOS[0]["id"] if TORNEIOS else None)
    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    def _track(event_name: str, payload: dict | None = None):
        """Chama ga_event se existir (não quebra a app se não existir)."""
        try:
            ga_event(event_name, payload or {})
        except Exception:
            pass

    def get_torneio(tid: str):
        for t in TORNEIOS:
            if str(t.get("id")) == str(tid):
                return t
        return TORNEIOS[0] if TORNEIOS else None

    def normalize_phone(phone: str) -> str:
        phone = (phone or "").strip()
        phone = re.sub(r"[^\d+]", "", phone)
        return phone

    def safe_slug(text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
        return text[:60] if text else "user"

    # ---- Sub-navegação (mostra 'Inscrição' só depois de escolher um torneio)
        if "show_inscricao" not in st.session_state:
            st.session_state.show_inscricao = False
        if "tour_view" not in st.session_state:
            st.session_state.tour_view = "🏆 Torneios"

        view_options = ["🏆 Torneios", "🔒 Organizador"]
        if st.session_state.show_inscricao:
            view_options.insert(1, "📝 Inscrição")

        # Se a opção desapareceu, garantir que não fica selecionada
        if st.session_state.tour_view not in view_options:
            st.session_state.tour_view = "🏆 Torneios"

        tour_view = st.radio("", view_options, horizontal=True, key="tour_view")
        st.divider()
    # ---- Sub-tab: Cards de torneios
    if tour_view == "🏆 Torneios":
        st.caption("Escolhe um torneio e clica em **Inscrever**.")

        if not TORNEIOS:
            st.warning("Ainda não tens torneios configurados na aba 'Torneios'.")
            st.info("Dica: cria uma aba chamada **Torneios** com colunas: id, nome, data, local, descricao, imagem_url, vagas, ativo (TRUE/FALSE).")

        else:
            cols = st.columns(3 if not is_mobile else 1)
            for i, t in enumerate(TORNEIOS):
                with cols[i % len(cols)]:
                    img = (t.get("img") or "").strip()
                    if img:
                        try:
                            st.image(img, use_container_width=True)
                        except Exception:
                            st.caption("(imagem indisponível)")
                    st.markdown(f"**{t.get('nome','')}**")
                    st.caption(f"📅 {t.get('data','')} · 📍 {t.get('local','')}")
                    if t.get("descricao"):
                        st.write(t["descricao"])

                    if st.button("Inscrever", key=f"insc_{t.get('id')}"):
                        st.session_state.torneio_sel = t.get("id")
                        st.session_state.show_inscricao = True
                        st.session_state.tour_view = "📝 Inscrição"
                        _track("torneio_select", {"torneio_id": t.get("id"), "torneio_nome": t.get("nome")})
                        st.rerun()

    # ---- Sub-tab: Formulário
    if tour_view == "📝 Inscrição":
        cols_nav = st.columns([1, 3])
        with cols_nav[0]:
            if st.button("⬅️ Voltar", key="voltar_torneios"):
                st.session_state.tour_view = "🏆 Torneios"
                st.rerun()
        with cols_nav[1]:
            if st.button("✖️ Fechar inscrição", key="fechar_inscricao"):
                st.session_state.show_inscricao = False
                st.session_state.tour_view = "🏆 Torneios"
                st.rerun()
        st.divider()
        if not TORNEIOS:
            st.warning("Ainda não há torneios ativos para inscrição.")
        elif not has_google_secrets():
            st.error("Falta configurar `GCP_SERVICE_ACCOUNT` e `SHEET_ID` nos Secrets do Streamlit Cloud.")
        elif not has_dropbox_token():
            st.error("Falta configurar `DROPBOX_TOKEN` nos Secrets do Streamlit Cloud.")
        else:
            torneio = get_torneio(st.session_state.torneio_sel)
            if not torneio:
                st.warning("Sem torneio selecionado.")
            else:
                st.markdown(f"**Torneio:** {torneio.get('nome','')}  \n📅 {torneio.get('data','')} · 📍 {torneio.get('local','')}")
                with st.form("form_inscricao", clear_on_submit=True):
                    nome = st.text_input("Nome completo")
                    telefone = st.text_input("Número de telefone")
                    foto = st.file_uploader("Fotografia", type=["jpg", "jpeg", "png"])
                    ok = st.form_submit_button("Submeter inscrição")

                if ok:
                    nome = (nome or "").strip()
                    telefone_norm = normalize_phone(telefone)

                    if not nome:
                        st.error("Falta o nome.")
                    elif not telefone_norm:
                        st.error("Falta o número de telefone.")
                    elif foto is None:
                        st.error("Falta a fotografia.")
                    else:
                        try:
                            save_inscricao(torneio, nome, telefone_norm, foto)
                            _track("torneio_signup_submit", {"torneio_id": torneio.get("id")})
                            st.success("Inscrição submetida com sucesso ✅")
                            st.caption("A foto foi enviada para o Dropbox (na pasta configurada).")
                        except Exception as e:
                            st.error("Erro ao guardar inscrição.")
                            st.exception(e)

    # ---- Sub-tab: Organizador
    if tour_view == "🔒 Organizador":
        st.caption("Área privada do organizador: lista de inscritos e fotos.")

        admin_pw = st.secrets.get("ADMIN_PASSWORD", None)
        if admin_pw is None:
            st.warning("Define `ADMIN_PASSWORD` em Secrets para ativar login. (Por agora vou permitir acesso.)")
            st.session_state.admin_ok = True

        if not st.session_state.admin_ok:
            pw = st.text_input("Password", type="password")
            if st.button("Entrar"):
                if pw == admin_pw:
                    st.session_state.admin_ok = True
                    st.rerun()
                else:
                    st.error("Password inválida.")
        else:
            if not has_google_secrets():
                st.error("Falta configurar `GCP_SERVICE_ACCOUNT` e `SHEET_ID` nos Secrets.")
            else:
                try:
                    df_insc = read_sheet()
                except Exception as e:
                    st.error("Erro ao ler inscrições da Google Sheet.")
                    st.exception(e)
                    st.stop()

                if df_insc.empty:
                    st.info("Ainda não há inscrições.")
                else:
                    # filtro por torneio
                    if "torneio_id" not in df_insc.columns:
                        st.error("A Sheet 'inscricoes' não tem a coluna 'torneio_id'. Confere os headers.")
                        st.dataframe(df_insc, use_container_width=True, hide_index=True)
                        st.stop()

                    torneio_ids = sorted(df_insc["torneio_id"].astype(str).unique().tolist())
                    sel = st.selectbox("Filtrar por torneio", ["(Todos)"] + torneio_ids)

                    view = df_insc.copy()
                    if sel != "(Todos)":
                        view = view[view["torneio_id"].astype(str) == sel]

                    st.dataframe(
                        view.drop(columns=[c for c in ["storage"] if c in view.columns]),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.markdown("### Fotos (últimas 12)")
                    tail = view.tail(12)

                    for _, r in tail.iterrows():
                        st.write(f"**{r.get('nome','')}** — {r.get('telefone','')} · {r.get('timestamp','')}")
                        foto_url = (r.get("foto_url", "") or "").strip()
                        if foto_url:
                            st.image(foto_url, use_container_width=True)
                            st.markdown(f"[Abrir no Dropbox]({foto_url})")
                        else:
                            st.caption("Sem foto_url guardado (verifica o upload para Dropbox).")
                        st.divider()


with tab_pts:
    render_points_calculator()

# -------------------------------------------------
# RANKINGS TAB (link)
# -------------------------------------------------
with tab_rank:
    st.subheader("Rankings (TieSports)")
    st.caption("Abre o ranking no site oficial.")
    st.link_button("🏆 Abrir Rankings", "https://tour.tiesports.com/fpp/weekly_rankings", use_container_width=True)
