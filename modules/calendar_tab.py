import streamlit as st
import pandas as pd
import datetime as dt
from urllib.parse import urlparse, quote_plus

from modules.storage import read_sheet  # caso precises no futuro


def render_calendar(
    find_latest_calendar_pdf_url,
    infer_year_from_pdf_url,
    download_pdf_bytes,
    parse_calendar_pdf,
    normalize_and_dedupe,
    build_local_dash_org,
    month_sort_key,
    is_mobile,
):
    left, right = st.columns([1, 1])
    with right:
        if st.button("⟲ Actualizar", help="Ignora cache e volta a detectar o PDF mais recente"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("A detectar o PDF mais recente e a extrair dados…"):
        try:
            pdf_url = find_latest_calendar_pdf_url()
            pdf_name = pdf_url.split("/")[-1]
            year = infer_year_from_pdf_url(pdf_url)
            pdf_bytes = download_pdf_bytes(pdf_url)

            df = parse_calendar_pdf(pdf_bytes, year=year)
            df = normalize_and_dedupe(df)

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
                st.error("Ainda não há dados em cache.")
                st.stop()

    st.markdown(f"""
    <div class="topbar">
      <div class="top-title">Calendário FPPadel</div>
      <div class="top-sub">ABS e JOV • actualizado automaticamente • Maps</div>
    </div>
    """, unsafe_allow_html=True)

    st.link_button("Abrir PDF original", pdf_url)

    if df.empty:
        st.error("Não consegui extrair linhas do PDF.")
        st.stop()

    df["Local"] = df.apply(build_local_dash_org, axis=1)
    df["Mapa"] = df["Local"].apply(
        lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}"
    )

    tab_abs, tab_jov, tab_all = st.tabs(["ABS", "JOV", "ABS + JOV"])

    def render_view(div_value):
        base = df.copy()
        if div_value in ("ABS", "JOV"):
            base = base[base["DIV"] == div_value].copy()

        st.dataframe(
            base[["Data (mês + dia)", "DIV", "Categorias", "Classe", "Local", "Mapa"]],
            use_container_width=True,
            hide_index=True,
        )

    with tab_abs:
        render_view("ABS")
    with tab_jov:
        render_view("JOV")
    with tab_all:
        render_view(None)
