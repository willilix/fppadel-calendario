import streamlit as st

from modules.storage import read_torneios, read_sheet, save_inscricao, normalize_phone


def render_tournaments(is_mobile: bool):
    st.markdown("""
    <div class="topbar">
      <div class="top-title">Torneios</div>
      <div class="top-sub">Inscrições dentro da app • com foto • área do organizador</div>
    </div>
    """, unsafe_allow_html=True)

    TORNEIOS = read_torneios()

    if "tour_view" not in st.session_state:
        st.session_state.tour_view = "lista"
    if "torneio_sel" not in st.session_state:
        st.session_state.torneio_sel = None
    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    def get_torneio(tid: str):
        for t in TORNEIOS:
            if str(t.get("id")) == str(tid):
                return t
        return None

    # ------------------------
    # LISTA DE TORNEIOS
    # ------------------------
    if st.session_state.tour_view == "lista":
        st.caption("Escolhe um torneio e clica em **Inscrever**.")

        if not TORNEIOS:
            st.warning("Ainda não tens torneios configurados na aba 'Torneios'.")
            st.info("Cria a aba **Torneios** com colunas: id, nome, data, local, descricao, imagem_url, vagas, ativo (TRUE/FALSE).")
            return

        def ir_para_inscricao(tid):
            st.session_state.torneio_sel = tid
            st.session_state.tour_view = "inscricao"

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

                st.button(
                    "Inscrever",
                    key=f"insc_{t.get('id')}",
                    on_click=ir_para_inscricao,
                    args=(t.get("id"),),
                )

        st.divider()

    # ------------------------
    # FORMULÁRIO DE INSCRIÇÃO
    # ------------------------
    if st.session_state.tour_view == "inscricao":
        torneio = get_torneio(st.session_state.torneio_sel)
        if not torneio:
            st.warning("Sem torneio selecionado.")
            st.session_state.tour_view = "lista"
            st.session_state.torneio_sel = None
            st.rerun()

        st.markdown(f"## 📝 Inscrição — {torneio.get('nome','')}")

        if st.button("← Voltar"):
            st.session_state.tour_view = "lista"
            st.session_state.torneio_sel = None
            st.rerun()

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
                    st.success("Inscrição submetida com sucesso ✅")
                except Exception as e:
                    st.error("Erro ao guardar inscrição.")
                    st.exception(e)

        st.divider()

    # ------------------------
    # ORGANIZADOR
    # ------------------------
    st.markdown("### 🔒 Área do Organizador")

    admin_pw = st.secrets.get("ADMIN_PASSWORD", None)
    if admin_pw is None:
        st.warning("Define `ADMIN_PASSWORD` em Secrets para ativar login.")
        return

    if not st.session_state.admin_ok:
        pw = st.text_input("Password", type="password")
        if st.button("Entrar"):
            if pw == admin_pw:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Password inválida.")
        return

    try:
        df_insc = read_sheet()
    except Exception as e:
        st.error("Erro ao ler inscrições da Google Sheet.")
        st.exception(e)
        return

    if df_insc.empty:
        st.info("Ainda não há inscrições.")
        return

    torneio_ids = sorted(df_insc["torneio_id"].astype(str).unique().tolist()) if "torneio_id" in df_insc.columns else []
    sel = st.selectbox("Filtrar por torneio", ["(Todos)"] + torneio_ids)

    view = df_insc.copy()
    if sel != "(Todos)" and "torneio_id" in view.columns:
        view = view[view["torneio_id"].astype(str) == sel]

    st.dataframe(
        view.drop(columns=[c for c in ["storage"] if c in view.columns]),
        use_container_width=True,
        hide_index=True,
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
            st.caption("Sem foto_url guardado.")
        st.divider()
