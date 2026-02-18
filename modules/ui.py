import os
import base64
import uuid
import streamlit as st
import streamlit.components.v1 as components


# ----------------------------
# iOS Home Screen icon
# ----------------------------
def set_ios_home_icon(path: str = "icon.png"):
    if not os.path.exists(path):
        return

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

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

            // favicon (ajuda nalguns casos)
            let icon = document.querySelector("link[rel='icon']");
            if (!icon) {{
              icon = document.createElement("link");
              icon.rel = "icon";
              document.head.appendChild(icon);
            }}
            icon.href = href;

            // PWA-ish
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


# ----------------------------
# STAGING badge
# ----------------------------
def render_staging_badge():
    if not os.path.exists("STAGING"):
        return

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
        
/* =========================================
   RADIO HORIZONTAL COMO TABS (PÍLULA)
========================================= */

div[role="radiogroup"]{
  display: flex !important;
  gap: 10px !important;
  flex-wrap: nowrap !important;
  margin-bottom: 20px !important;
}

div[role="radiogroup"] input[type="radio"]{
  display: none !important;
}

div[role="radiogroup"] > label{
  border-radius: 999px !important;
  padding: 10px 16px !important;
  border: 1px solid rgba(255,255,255,0.14) !important;
  background: rgba(255,255,255,0.06) !important;
  cursor: pointer !important;
  transition: all 0.18s ease-in-out !important;
}

div[role="radiogroup"] > label p{
  margin: 0 !important;
  font-weight: 600 !important;
  opacity: 0.85 !important;
}

div[role="radiogroup"] > label:hover{
  background: rgba(255,255,255,0.10) !important;
  transform: translateY(-1px) !important;
}

div[role="radiogroup"] > label:has(input:checked){
  background: linear-gradient(135deg, #1f6fff, #4ea1ff) !important;
  border-color: transparent !important;
  box-shadow: 0 8px 25px rgba(0,0,0,0.25) !important;
}

div[role="radiogroup"] > label:has(input:checked) p{
  opacity: 1 !important;
  color: white !important;
}

</style>
        <div class="staging-badge">🧪 STAGING</div>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------
# GA4 (server-side pageview via MP)
# ----------------------------
def ga4_track_pageview():
    # evita enviar 20 eventos por causa dos reruns
    if st.session_state.get("_ga_sent"):
        return
    st.session_state["_ga_sent"] = True

    measurement_id = st.secrets.get("GA_MEASUREMENT_ID", "")
    api_secret = st.secrets.get("GA_API_SECRET", "")
    if not measurement_id or not api_secret:
        return

    import requests

    client_id = st.session_state.get("_ga_client_id")
    if not client_id:
        client_id = f"{uuid.uuid4()}.{uuid.uuid4()}"
        st.session_state["_ga_client_id"] = client_id

    url = f"https://www.google-analytics.com/mp/collect?measurement_id={measurement_id}&api_secret={api_secret}"
    payload = {
        "client_id": client_id,
        "events": [{"name": "page_view", "params": {"page_title": "FPPadel Calendário", "page_location": "streamlit_app"}}],
    }

    try:
        requests.post(url, json=payload, timeout=3)
    except Exception:
        pass


# ----------------------------
# GA4 client-side tag + helpers
# ----------------------------
def inject_ga_tag():
    mid = st.secrets.get("GA_MEASUREMENT_ID", "")
    if not mid:
        return

    components.html(
        f"""
        <script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>
        <script>
          window.dataLayer = window.dataLayer || [];
          function gtag(){{dataLayer.push(arguments);}}
          gtag('js', new Date());
          gtag('config', '{mid}', {{
            page_path: window.location.pathname,
            page_title: document.title,
            page_location: window.location.href,
            send_page_view: true
          }});
        </script>
        """,
        height=0,
    )


def ga_event(name: str, params: dict | None = None):
    params = params or {}
    js_params = str(params).replace("'", '"')
    components.html(
        f"""
        <script>
          (function() {{
            const params = {js_params};
            if (typeof gtag === 'function') {{
              gtag('event', '{name}', params);
              return;
            }}
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

            bindTabs();
            const obs = new MutationObserver(() => bindTabs());
            obs.observe(document.body, { childList: true, subtree: true });
          })();
        </script>
        """,
        height=0,
    )


# ----------------------------
# Mobile detection (best-effort)
# ----------------------------
def init_mobile_detection() -> bool:
    if "is_mobile" not in st.session_state:
        st.session_state["is_mobile"] = False

    components.html(
        """
        <script>
          try {
            const isMobile = window.matchMedia("(max-width: 768px)").matches;
            window.parent.postMessage(
              { type: "streamlit:setSessionState", key: "is_mobile", value: !!isMobile },
              "*"
            );
          } catch(e) {}
        </script>
        """,
        height=0,
    )
    return bool(st.session_state.get("is_mobile", False))


# ----------------------------
# Premium CSS + Logo
# ----------------------------
def render_premium_css():
    st.markdown(
        """
<style>
.block-container {
    padding-top: 1.1rem;
    padding-bottom: 3rem;
    max-width: 1120px;
}
header { visibility: hidden; }

.stApp {
    background:
        radial-gradient(1200px 600px at 50% -10%, rgba(10,132,255,0.18), rgba(0,0,0,0) 55%),
        linear-gradient(180deg, #0B0B10 0%, #07070A 100%);
    color: rgba(237,237,243,0.96);
}

a, a:visited { color: #0A84FF !important; text-decoration: none; }
a:hover { text-decoration: underline; }

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

.top-title { font-weight: 800; font-size: 1.4rem; margin: 0; }
.top-sub { color: rgba(237,237,243,0.6); font-size: 0.95rem; }

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

.metric {
    border-radius: 20px;
    background: rgba(18,18,26,0.75);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 18px 60px rgba(0,0,0,0.55);
    padding: 16px;
    transition: all 0.25s ease;
}
.metric:hover { transform: translateY(-2px); box-shadow: 0 24px 70px rgba(0,0,0,0.65); }
.metric .label { color: rgba(237,237,243,0.6); font-size: 0.82rem; }
.metric .value { font-weight: 800; font-size: 1.2rem; margin-top: 6px; }
.metric .hint { color: rgba(237,237,243,0.5); font-size: 0.8rem; }

.card {
    border-radius: 24px;
    background: rgba(18,18,26,0.75);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 18px 60px rgba(0,0,0,0.55);
    padding: 18px;
    margin-bottom: 14px;
    transition: all 0.25s ease;
}
.card:hover { transform: translateY(-2px); box-shadow: 0 24px 70px rgba(0,0,0,0.65); }
.card .title { font-weight: 800; font-size: 1.05rem; }
.card .row { margin-top: 8px; font-size: 0.92rem; color: rgba(237,237,243,0.75); }

div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div { border-radius: 16px !important; }

.stButton button {
    border-radius: 16px !important;
    padding: 0.55rem 1rem !important;
    font-weight: 600;
}

/* Só botão primary (Inscrever) */
.stButton button[kind="primary"] {
    background: linear-gradient(135deg, #FF453A, #FF2D55) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 8px 20px rgba(255,69,58,0.35);
}

.stButton button[kind="primary"]:hover {
    background: linear-gradient(135deg, #FF3B30, #FF375F) !important;
    transform: translateY(-1px);
}

.stTabs [data-baseweb="tab-list"] { gap: 8px; }
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

[data-testid="stDataFrame"] {
    border-radius: 20px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.1);
    box-shadow: 0 18px 60px rgba(0,0,0,0.5);
}

/* =========================================
   RADIO HORIZONTAL COMO TABS (PÍLULA)
========================================= */

div[role="radiogroup"]{
  display: flex !important;
  gap: 10px !important;
  flex-wrap: nowrap !important;
  margin-bottom: 20px !important;
}

div[role="radiogroup"] input[type="radio"]{
  display: none !important;
}

div[role="radiogroup"] > label{
  border-radius: 999px !important;
  padding: 10px 16px !important;
  border: 1px solid rgba(255,255,255,0.14) !important;
  background: rgba(255,255,255,0.06) !important;
  cursor: pointer !important;
  transition: all 0.18s ease-in-out !important;
}

div[role="radiogroup"] > label p{
  margin: 0 !important;
  font-weight: 600 !important;
  opacity: 0.85 !important;
}

div[role="radiogroup"] > label:hover{
  background: rgba(255,255,255,0.10) !important;
  transform: translateY(-1px) !important;
}

div[role="radiogroup"] > label:has(input:checked){
  background: linear-gradient(135deg, #1f6fff, #4ea1ff) !important;
  border-color: transparent !important;
  box-shadow: 0 8px 25px rgba(0,0,0,0.25) !important;
}

div[role="radiogroup"] > label:has(input:checked) p{
  opacity: 1 !important;
  color: white !important;
}

</style>
        """,
        unsafe_allow_html=True,
    )


def render_logo(logo_path: str = "armadura.png", subtitle: str = "App oficial dos 6 zeritas - Powered by Grupo do 60"):
    st.markdown(
        """
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
    height:380px;
    width:auto;
    object-fit:contain;
    filter: drop-shadow(0 20px 40px rgba(0,0,0,0.45))
            drop-shadow(0 6px 12px rgba(0,0,0,0.35));
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

/* =========================================
   RADIO HORIZONTAL COMO TABS (PÍLULA)
========================================= */

div[role="radiogroup"]{
  display: flex !important;
  gap: 10px !important;
  flex-wrap: nowrap !important;
  margin-bottom: 20px !important;
}

div[role="radiogroup"] input[type="radio"]{
  display: none !important;
}

div[role="radiogroup"] > label{
  border-radius: 999px !important;
  padding: 10px 16px !important;
  border: 1px solid rgba(255,255,255,0.14) !important;
  background: rgba(255,255,255,0.06) !important;
  cursor: pointer !important;
  transition: all 0.18s ease-in-out !important;
}

div[role="radiogroup"] > label p{
  margin: 0 !important;
  font-weight: 600 !important;
  opacity: 0.85 !important;
}

div[role="radiogroup"] > label:hover{
  background: rgba(255,255,255,0.10) !important;
  transform: translateY(-1px) !important;
}

div[role="radiogroup"] > label:has(input:checked){
  background: linear-gradient(135deg, #1f6fff, #4ea1ff) !important;
  border-color: transparent !important;
  box-shadow: 0 8px 25px rgba(0,0,0,0.25) !important;
}

div[role="radiogroup"] > label:has(input:checked) p{
  opacity: 1 !important;
  color: white !important;
}

</style>
        """,
        unsafe_allow_html=True,
    )

    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        st.markdown(
            f"""
            <div class="logo-wrap">
              <img class="logo-img" src="data:image/png;base64,{b64}" alt="armadura" />
              <div class="logo-text">{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="logo-wrap">
              <div class="logo-text">{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_global_ui(icon_path: str = "icon.png", logo_path: str = "armadura.png"):
    render_staging_badge()
    set_ios_home_icon(icon_path)
    render_premium_css()
    render_logo(logo_path)
    inject_ga_tag()
    ga4_track_pageview()
