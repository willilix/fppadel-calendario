import io
import streamlit as st

from modules.storage import read_torneios, read_sheet, save_inscricao, normalize_phone



from datetime import datetime, date

def _truthy(v) -> bool:
    s = "" if v is None else str(v).strip().lower()
    return s in ("true", "1", "yes", "y", "sim", "s", "on")

def _falsey(v) -> bool:
    s = "" if v is None else str(v).strip().lower()
    return s in ("false", "0", "no", "n", "nao", "não", "off")

def _parse_date(v):
    \"\"\"Parse dates coming from Google Sheets.
    Accepts: YYYY-MM-DD, YYYY/MM/DD, DD/MM/YYYY, DD-MM-YYYY, or datetime-like.
    Returns: date or None.
    \"\"\"
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None

    # Try ISO first
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    # Try PT common formats
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    # Last resort: try dateutil if available
    try:
        from dateutil import parser  # type: ignore
        return parser.parse(s, dayfirst=True).date()
    except Exception:
        return None

def _inscricoes_estado(t: dict):
    \"\"\"Decide if 'Inscrever' should be enabled for a tournament dict.
    Sheet columns supported (any of these):
      - inscricoes_abertas (TRUE/FALSE) [manual override]
      - inscricoes_inicio  (date)
      - inscricoes_fim     (date)
    Also accepts aliases:
      - abertas/aberta, inicio_inscricoes, fim_inscricoes
    Priority:
      1) manual override inscricoes_abertas if provided (TRUE/FALSE)
      2) date window check if inicio/fim provided
      3) default open
    Returns (enabled: bool, reason: str|None)
    \"\"\"
    # 1) Manual override
    manual = (
        t.get("inscricoes_abertas")
        if t.get("inscricoes_abertas") is not None and str(t.get("inscricoes_abertas")).strip() != ""
        else t.get("abertas") if t.get("abertas") is not None and str(t.get("abertas")).strip() != "" else
        t.get("aberta")
    )
    if manual is not None and str(manual).strip() != "":
        if _truthy(manual):
            return True, None
        if _falsey(manual):
            return False, "Inscrições fechadas"
        # if weird value, ignore and continue

    # 2) Date window
    inicio = _parse_date(t.get("inscricoes_inicio") or t.get("inicio_inscricoes") or t.get("inicio"))
    fim = _parse_date(t.get("inscricoes_fim") or t.get("fim_inscricoes") or t.get("fim"))

    today = date.today()

    if inicio and today < inicio:
        return False, f"Abre em {inicio.strftime('%d/%m/%Y')}"
    if fim and today > fim:
        return False, "Inscrições fechadas"
    # If within window (or only one bound satisfied), open
    if inicio or fim:
        return True, None

    # 3) Default
    return True, None

class _BytesUpload:
    """Fallback object that mimics Streamlit's UploadedFile enough for our storage layer."""
    def __init__(self, name: str, content_type: str, data: bytes):
        self.name = name or "foto.jpg"
        self.type = content_type or "image/jpeg"
        self._data = data or b""

    def getvalue(self) -> bytes:
        return self._data

    def getbuffer(self):
        return memoryview(self._data)

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._data
        return self._data[:n]


def _stash_upload(uploader_key: str, stash_key: str):
    """Keep the uploaded file bytes in session_state to survive reruns/form quirks."""
    up = st.file_uploader("Fotografia", type=["jpg", "jpeg", "png", "webp"], key=uploader_key)
    if up is not None:
        st.session_state[stash_key] = {
            "name": getattr(up, "name", "foto.jpg"),
            "type": getattr(up, "type", "image/jpeg"),
            "bytes": up.getvalue(),
        }
    return up


def _get_stashed_upload(stash_key: str):
    payload = st.session_state.get(stash_key)
    if not payload:
        return None
    b = payload.get("bytes") or b""
    if not b:
        return None
    return _BytesUpload(payload.get("name", "foto.jpg"), payload.get("type", "image/jpeg"), b)


def _clear_inscricao_state(*keys: str):
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def render_tournaments(is_mobile: bool):
    st.markdown(
        """
        <div class="topbar">
          <div class="top-title">Torneios</div>
          <div class="top-sub">Torneios activos</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
            st.info(
                "Cria a aba **Torneios** com colunas: id, nome, data, local, descricao, imagem_url, vagas, ativo (TRUE/FALSE)."
            )
            return

        def ir_para_inscricao(tid):
            st.session_state.torneio_sel = tid
            st.session_state.tour_view = "inscricao"
            st.session_state.main_tab = 1  # força Torneios

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

                # Controlar se o torneio está ativo (permite desativar botão via coluna "ativo")
                ativo_raw = str(t.get("ativo", "TRUE")).strip().lower()
                ativo = ativo_raw in ("true", "1", "yes", "sim")

                
        enabled, reason = _inscricoes_estado(t)

        st.button(
            "Inscrever" if enabled else (reason or "Inscrições fechadas"),
            key=f"insc_{t.get('id')}",
            type="primary",
            on_click=ir_para_inscricao if enabled else None,
            args=(t.get("id"),) if enabled else None,
            disabled=not enabled,
        )
}",
                    type="primary",
                    on_click=ir_para_inscricao,
                    args=(t.get("id"),),
                    disabled=not ativo,
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
            # limpa também o estado do formulário para não ficar "preso"
            _clear_inscricao_state("insc_nome", "insc_tel", "insc_foto", "insc_foto_stash")
            st.session_state.tour_view = "lista"
            st.session_state.torneio_sel = None
            st.rerun()

        # Chaves estáveis para evitar conflitos entre torneios
        uploader_key = "insc_foto"
        stash_key = "insc_foto_stash"

        with st.form("form_inscricao", clear_on_submit=False):
            nome = st.text_input("Nome completo", key="insc_nome")
            telefone = st.text_input("Número de telefone", key="insc_tel")
            # guarda sempre bytes em session_state quando o utilizador escolhe a foto
            foto_live = _stash_upload(uploader_key, stash_key)

            ok = st.form_submit_button("Submeter inscrição")

        if ok:
            nome = (nome or "").strip()
            telefone_norm = normalize_phone(telefone)

            # tenta usar o upload "vivo"; se o Streamlit o limpar no rerun, usa o stash
            foto = foto_live if foto_live is not None else _get_stashed_upload(stash_key)

            if not nome:
                st.error("Falta o nome.")
            elif not telefone_norm:
                st.error("Falta o número de telefone.")
            elif foto is None:
                st.error("Falta a fotografia.")
            else:
                try:
                    # guardamos e exigimos que não seja "silent fail"
                    res = save_inscricao(torneio, nome, telefone_norm, foto)

                    # Se a tua save_inscricao devolver algo, mostramos (ajuda a diagnosticar)
                    if isinstance(res, (tuple, list)) and len(res) >= 1:
                        maybe_url = (res[0] or "").strip() if isinstance(res[0], str) else ""
                        if maybe_url:
                            st.success("Inscrição submetida com sucesso ✅")
                            st.caption(f"foto_url: {maybe_url}")
                        else:
                            st.warning("Inscrição gravada, mas o foto_url veio vazio. (verifica o upload/storage)")
                    else:
                        st.success("Inscrição submetida com sucesso ✅")

                    # limpa o formulário depois de sucesso
                    _clear_inscricao_state("insc_nome", "insc_tel", uploader_key, stash_key)

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

    torneio_ids = (
        sorted(df_insc["torneio_id"].astype(str).unique().tolist())
        if "torneio_id" in df_insc.columns
        else []
    )
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
