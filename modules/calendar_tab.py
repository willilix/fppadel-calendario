import os
import datetime as dt
from urllib.parse import urlparse, quote_plus

import pandas as pd
import streamlit as st


def render_calendar(
    *,
    find_latest_calendar_pdf_url,
    infer_year_from_pdf_url,
    download_pdf_bytes,
    parse_calendar_pdf,
    normalize_and_dedupe,
    build_local_dash_org,
    month_sort_key,
    is_mobile: bool,
):
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
    df["Local"] = (
        df["Local"].astype("string")
        .fillna("")
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .replace({"": pd.NA})
    )

    df["Mapa"] = df["Local"].apply(
        lambda x: f"https://www.google.com/maps/search/?api=1&query={quote_plus(str(x))}"
    )

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
        view["Data_Fim"] = view["Data_Fim"].fillna(view["Data_Inicio"])
        view["Data_Inicio"] = view["Data_Inicio"].fillna(view["Data_Fim"])

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

        metrics_df = base.copy()
        metrics_df["Data_Inicio"] = pd.to_datetime(metrics_df["Data_Inicio"], errors="coerce")
        metrics_df["Data_Fim"] = pd.to_datetime(metrics_df["Data_Fim"], errors="coerce")
        metrics_df["Data_Fim"] = metrics_df["Data_Fim"].fillna(metrics_df["Data_Inicio"])
        metrics_df["Data_Inicio"] = metrics_df["Data_Inicio"].fillna(metrics_df["Data_Fim"])
       # Se Data_Fim ficou antes de Data_Inicio, é quase sempre evento a cruzar mês (ex.: 31/01 a 02/02)
        mask = (
            metrics_df["Data_Inicio"].notna()
            & metrics_df["Data_Fim"].notna()
            & (metrics_df["Data_Fim"] < metrics_df["Data_Inicio"])
        )
        metrics_df.loc[mask, "Data_Fim"] = metrics_df.loc[mask, "Data_Fim"] + pd.DateOffset(months=1)

        # Próximo evento
        next_date = None
        future = metrics_df[
            metrics_df["Data_Inicio"].notna() &
            (metrics_df["Data_Inicio"].dt.date >= today)
        ]
        if not future.empty:
            sort_cols = [c for c in ["Data_Inicio", "DIV", "Categorias"] if c in future.columns]
            future = future.sort_values(sort_cols if sort_cols else ["Data_Inicio"])
            next_date = future.iloc[0]["Data_Inicio"]

        # Eventos a decorrer este mês
        start_month = dt.date(today.year, today.month, 1)
        end_month = (dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)) if today.month != 12 else dt.date(today.year, 12, 31)

        this_month = metrics_df[
            metrics_df["Data_Inicio"].notna() &
            metrics_df["Data_Fim"].notna() &
            (metrics_df["Data_Inicio"].dt.date <= end_month) &
            (metrics_df["Data_Fim"].dt.date >= start_month)
        ]
        this_month_count = len(this_month)

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
            nxt = next_date.strftime("%d/%m") if next_date is not None else "—"
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
           
        if "Data_Inicio" in view.columns:
            view = view.sort_values(["Data_Inicio", "DIV"], na_position="last")
        # Ordenação cronológica (garante ordem correta dentro do mês)
if "Data_Inicio" in view.columns:
    view = view.sort_values(
        ["Data_Inicio", "DIV", "Categorias"],
        na_position="last",
        kind="mergesort",
    )

        st.markdown("### Actividades")

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
