from __future__ import annotations

import os
import re
import datetime as dt
from urllib.parse import urlparse, quote_plus

import pandas as pd
import streamlit as st



def _clean_text(x) -> str:
    s = "" if x is None else str(x)
    s = re.sub(r"\s+", " ", s).strip()
    return s


MONTHS_PT = {
    "janeiro","fevereiro","março","marco","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"
}

def _is_month_only(s: str) -> bool:
    if not s:
        return False
    t = s.strip().lower()
    return t in MONTHS_PT



def _extract_local_from_text(txt: str) -> str:
    s = _clean_text(txt)
    if not s:
        return ""
    # Padrão típico: "FIP Bronze Portimão FPP ..." / "FIP Silver Lisboa FPP ..."
    m = re.search(r"\bFIP\s+(?:Bronze|Silver|Gold|Platinum)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\- ]{2,60})\b", s, re.I)
    if m:
        cand = _clean_text(m.group(1))
        # corta se vier com "FPP" ou classes coladas
        cand = re.split(r"\bFPP\b|\bF\d\b|\bM\d\b|\bFIP\b", cand, flags=re.I)[0]
        cand = _clean_text(cand)
        cand = re.sub(r"^(Bronze|Silver|Gold|Platinum)\s+", "", cand, flags=re.I).strip()
        if cand and not _is_month_only(cand):
            return cand

    # Se houver uma cidade conhecida dentro do texto, usa-a
    cities = [
        "Portimão","Portimao","Lisboa","Porto","Braga","Setúbal","Setubal","Faro","Coimbra","Aveiro","Leiria",
        "Viseu","Évora","Evora","Guimarães","Guimaraes","Cascais","Sintra","Albufeira","Loulé","Loule",
        "Olhão","Olhao","Tavira","Lagos","Ericeira","Matosinhos"
    ]
    for c in cities:
        if re.search(rf"\b{re.escape(c)}\b", s, re.I):
            return c
    return ""


def _pick_first(row, cols):
    for c in cols:
        if c in row and pd.notna(row[c]):
            v = _clean_text(row[c])
            if v:
                return v
    return ""

def _infer_local(row, build_local_dash_org):
    """Tenta construir 'Local' de forma robusta.
    1) Usa a função original build_local_dash_org(row)
    2) Fallback: tenta colunas comuns que podem ter mudado no PDF
    3) Fallback final: procura em todas as colunas string por algo que pareça local
    """
    try:
        v = build_local_dash_org(row)
        v = _clean_text(v)
        if v and not _is_month_only(v):
            return v
    except Exception:
        pass

    # Colunas mais comuns (variam conforme o PDF)
    preferred = [
        "Local", "Localidade", "LOCAL", "Local (Org)",
        "Clube", "Clube / Organização", "Clube/Organização", "Organização", "Organizacao", "Org", "ORGANIZAÇÃO",
        "Cidade", "Concelho", "Distrito",
        "Pavilhão", "Pavilhao", "Complexo", "Campo",
    ]
    v = _pick_first(row, preferred)
    if v and not _is_month_only(v):
        return v

    # Tentar extrair local a partir de texto (ex: "FIP Bronze Portimão FPP ...")
    for c in ("Categorias", "Categoria", "Actividade", "Atividade", "Evento", "Prova", "Classe"):
        if c in row and pd.notna(row[c]):
            cand = _extract_local_from_text(row[c])
            if cand:
                return cand

    # Algumas vezes o local vem dentro de 'Categorias' ou 'Classe' (ex: "... — Lisboa")
    for c in ("Categorias", "Classe"):
        if c in row and pd.notna(row[c]):
            txt = _clean_text(row[c])
            # captura um sufixo depois de " - " / " — " / " | "
            m = re.search(r"(?:\s[-—|]\s)([^-—|]{3,60})$", txt)
            if m:
                cand = _clean_text(m.group(1))
                if cand:
                    return cand

    # Fallback final: varrer todos os campos por um candidato plausível
    # (evita datas e siglas curtas)
    best = ""
    for c, val in row.items():
        # Evitar confundir mês (da coluna Data/Local) com um local real
        if str(c).strip().lower() in ("data (mês + dia)", "data", "mes", "mês"):
            continue
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        s = _clean_text(val)
        if not s:
            continue
        if _is_month_only(s):
            continue
        if len(s) < 4:
            continue
        if re.fullmatch(r"\d{1,2}\s*a\s*\d{1,2}$", s):
            continue
        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}(?:\s*a\s*\d{1,2}[/-]\d{1,2})?", s):
            continue
        # preferir strings com letras e eventualmente parêntesis (clubes)
        score = 0
        if re.search(r"[A-Za-zÀ-ÿ]", s): score += 2
        if re.search(r"\b(Lisboa|Porto|Braga|Setúbal|Faro|Madeira|Açores|Coimbra|Aveiro|Leiria)\b", s, re.I): score += 3
        if re.search(r"\b(CP|Clube|Padel|Padel Club|CT|Associação|Associacao)\b", s, re.I): score += 2
        if len(s) <= 80: score += 1
        if score > 0 and score >= (0 if not best else -1):
            # escolhe o de melhor score e mais curto
            if (not best) or (score > 4 and len(s) < len(best)) or (score > 4 and best and score > 5):
                best = s
    return best


def _repair_cross_month_from_text(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Fallback para casos em que o parser não conseguiu inferir Data_Fim em eventos que atravessam meses,
    mas o texto "Data (mês + dia)" contém um final do tipo "a 1/03" ou "a 2/02".
    Só ajusta quando Data_Fim está vazia ou igual a Data_Inicio.
    """
    if df is None or df.empty:
        return df

    if "Data (mês + dia)" not in df.columns:
        return df

    # garantir datetime
    df["Data_Inicio"] = pd.to_datetime(df.get("Data_Inicio"), errors="coerce")
    df["Data_Fim"] = pd.to_datetime(df.get("Data_Fim"), errors="coerce")

    txt = df["Data (mês + dia)"].astype("string").fillna("")

    need = df["Data_Inicio"].notna() & (
        df["Data_Fim"].isna() | (df["Data_Fim"] == df["Data_Inicio"])
    )

    # padrão "a 1/03" (dia/mês)
    m = txt.str.extract(r"a\s*(\d{1,2})\s*/\s*(\d{1,2})", expand=True)
    end_day = pd.to_numeric(m[0], errors="coerce")
    end_month = pd.to_numeric(m[1], errors="coerce")

    ok = need & end_day.notna() & end_month.notna()

    if ok.any():
        # construir data fim
        end_dates = pd.to_datetime(
            {
                "year": year,
                "month": end_month.astype("Int64"),
                "day": end_day.astype("Int64"),
            },
            errors="coerce",
        )

        # se a data fim cair antes do início, assumir que é mês seguinte (ou, em casos raros, ano seguinte)
        bad = ok & end_dates.notna() & (end_dates < df["Data_Inicio"])
        end_dates.loc[bad] = end_dates.loc[bad] + pd.DateOffset(months=1)

        df.loc[ok & end_dates.notna(), "Data_Fim"] = end_dates.loc[ok & end_dates.notna()]

    return df


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

    st.markdown(
        f"""
    <div class="topbar">
      <div class="top-title">Calendário FPPadel</div>
      <div class="top-sub">ABS e JOV • actualizado automaticamente • Maps{new_badge}</div>
      <div style="display:flex; gap:10px; margin-top:10px; flex-wrap:wrap;">
        <span class="pill">PDF: {pdf_name}</span>
        <span class="pill">Ano: {year}</span>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    st.link_button("Abrir PDF original", pdf_url)

    if df is None or df.empty:
        st.error("Não consegui extrair linhas do PDF (o formato pode ter mudado).")
        st.stop()

    df["Local"] = df.apply(lambda r: _infer_local(r, build_local_dash_org), axis=1)
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
                    quick = st.selectbox(
                        "Datas",
                        ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"],
                        key=f"quick_{tab_key}",
                    )
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
                    quick = st.selectbox(
                        "Datas",
                        ["(Nenhum)", "Próximos 7 dias", "Próximos 30 dias", "Este mês"],
                        key=f"quick_{tab_key}",
                    )
                with c4:
                    search = st.text_input("Pesquisa", placeholder="Lisboa, FIP, S14, Madeira…", key=f"search_{tab_key}")
                st.form_submit_button("Aplicar")

        view = base.copy()

        # garantir datas como datetime (para filtros funcionarem)
        view["Data_Inicio"] = pd.to_datetime(view["Data_Inicio"], errors="coerce")
        view["Data_Fim"] = pd.to_datetime(view["Data_Fim"], errors="coerce")
        view["Data_Fim"] = view["Data_Fim"].fillna(view["Data_Inicio"])
        view["Data_Inicio"] = view["Data_Inicio"].fillna(view["Data_Fim"])

        # reparar cross-month quando o parser falhou (usando texto)
        view = _repair_cross_month_from_text(view, year=year)

        # caso Data_Fim tenha ficado antes (31/01 a 02/02 interpretado como 02/01)
        maskv = view["Data_Inicio"].notna() & view["Data_Fim"].notna() & (view["Data_Fim"] < view["Data_Inicio"])
        view.loc[maskv, "Data_Fim"] = view.loc[maskv, "Data_Fim"] + pd.DateOffset(months=1)

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
                (view["Data_Inicio"].notna())
                & (view["Data_Fim"].notna())
                & (view["Data_Inicio"].dt.date <= end)
                & (view["Data_Fim"].dt.date >= start)
            ]

        if search.strip():
            q = search.strip().lower()
            cols = ["Data (mês + dia)", "DIV", "Categorias", "Classe", "Local", "Mes"]
            mask = False
            for col in cols:
                mask = mask | view[col].astype(str).str.lower().str.contains(q, na=False)
            view = view[mask]

        # Ordenação cronológica (após filtros)
        if "Data_Inicio" in view.columns:
            view = view.sort_values(["Data_Inicio", "DIV", "Categorias"], na_position="last", kind="mergesort")

        # Metrics: total respeita filtros; "Este mês" e "Próximo" NÃO dependem do mês escolhido
        total = len(view)

        metrics_df = base.copy()
        metrics_df["Data_Inicio"] = pd.to_datetime(metrics_df["Data_Inicio"], errors="coerce")
        metrics_df["Data_Fim"] = pd.to_datetime(metrics_df["Data_Fim"], errors="coerce")
        metrics_df["Data_Fim"] = metrics_df["Data_Fim"].fillna(metrics_df["Data_Inicio"])
        metrics_df["Data_Inicio"] = metrics_df["Data_Inicio"].fillna(metrics_df["Data_Fim"])

        metrics_df = _repair_cross_month_from_text(metrics_df, year=year)

        mask = metrics_df["Data_Inicio"].notna() & metrics_df["Data_Fim"].notna() & (metrics_df["Data_Fim"] < metrics_df["Data_Inicio"])
        metrics_df.loc[mask, "Data_Fim"] = metrics_df.loc[mask, "Data_Fim"] + pd.DateOffset(months=1)

        # Próximo evento
        next_date = None
        future = metrics_df[metrics_df["Data_Inicio"].notna() & (metrics_df["Data_Inicio"].dt.date >= today)]
        if not future.empty:
            future = future.sort_values(["Data_Inicio", "DIV", "Categorias"], na_position="last")
            next_date = future.iloc[0]["Data_Inicio"]

        # Eventos a decorrer este mês (mês atual)
        start_month = dt.date(today.year, today.month, 1)
        end_month = (dt.date(today.year, today.month + 1, 1) - dt.timedelta(days=1)) if today.month != 12 else dt.date(today.year, 12, 31)

        this_month = metrics_df[
            metrics_df["Data_Inicio"].notna()
            & metrics_df["Data_Fim"].notna()
            & (metrics_df["Data_Inicio"].dt.date <= end_month)
            & (metrics_df["Data_Fim"].dt.date >= start_month)
        ]
        this_month_count = len(this_month)

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(
                f"""
            <div class="metric">
              <div class="label">Eventos</div>
              <div class="value">{total}</div>
              <div class="hint">na selecção actual</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with m2:
            nxt = next_date.strftime("%d/%m") if next_date is not None else "—"
            st.markdown(
                f"""
            <div class="metric">
              <div class="label">Próximo</div>
              <div class="value">{nxt}</div>
              <div class="hint">data de início</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with m3:
            st.markdown(
                f"""
            <div class="metric">
              <div class="label">Este mês</div>
              <div class="value">{this_month_count}</div>
              <div class="hint">eventos a decorrer</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        st.markdown("### Actividades")

        out = view[["Data (mês + dia)", "DIV", "Categorias", "Classe", "Local", "Mapa"]].copy()

        if is_mobile:
            for _, row in out.iterrows():
                title = row.get("Categorias") or row.get("Classe") or row.get("Local") or "Evento"
                pills = f'<span class="pill">{row["DIV"]}</span>'

                st.markdown(
                    f"""
                <div class="card">
                  <div class="title">{title}</div>
                  <div class="row">{row['Data (mês + dia)']} &nbsp; {pills}</div>
                  <div class="row"><b>Classe:</b> {row['Classe']}</div>
                  <div class="row"><b>Local:</b> {row['Local']}</div>
                  <div class="actions">
                    <a href="{row['Mapa']}" target="_blank">Abrir no Maps →</a>
                  </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )
        else:
            st.dataframe(
                out,
                use_container_width=True,
                hide_index=True,
                key=f"df_{tab_key}",
                column_config={"Mapa": st.column_config.LinkColumn("Mapa", display_text="Maps")},
            )

        st.download_button(
            "Download CSV (filtrado)",
            data=out.drop(columns=["Mapa"]).to_csv(index=False).encode("utf-8"),
            file_name=f"calendario_fppadel_{tab_key.lower()}_{pdf_name.replace('.pdf','')}.csv",
            mime="text/csv",
            key=f"dl_{tab_key}",
        )

    with tab_abs:
        render_view("ABS")
    with tab_jov:
        render_view("JOV")
    with tab_all:
        render_view(None)
