import datetime as dt
import time
import streamlit as st
import streamlit.components.v1 as components

from modules.betting_firestore import (
    list_markets, create_market, place_bet, get_market,
    resolve_market, cancel_market, get_balance, list_ledger, fs_client
)
from modules.betting_auth import (
    current_user, login_form, signup_form, logout,
    admin_panel_create_user, admin_panel_disable_user, admin_panel_list_users
)

# Admin gate (global)
try:
    from modules.admin_gate import is_admin
except Exception:
    def is_admin() -> bool:
        return False


def _parse_close_time(days_ahead: int, hour: int) -> dt.datetime:
    tz = dt.timezone.utc
    now = dt.datetime.now(tz)
    close = (now + dt.timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return close


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _remaining_seconds(close_time: dt.datetime | None) -> int | None:
    if not close_time:
        return None
    try:
        # ensure tz-aware
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=dt.timezone.utc)
    except Exception:
        pass
    diff = close_time - _now_utc()
    return int(diff.total_seconds())


def _format_remaining(close_time: dt.datetime | None) -> tuple[str, bool]:
    """Returns (label, urgent)."""
    secs = _remaining_seconds(close_time)
    if secs is None:
        return ("—", False)
    if secs <= 0:
        return ("Encerrado", True)

    urgent = secs <= 30 * 60  # < 30 min
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    if days > 0:
        return (f"{days}d {hours}h {minutes}m", urgent)
    if hours > 0:
        return (f"{hours}h {minutes}m", urgent)
    return (f"{minutes}m", urgent)


def _market_header_html(title: str, status_raw: str, close_time: dt.datetime | None) -> str:
    status = (status_raw or "").lower()
    remaining, urgent = _format_remaining(close_time)

    if status == "open":
        status_text = "OPEN"
        status_color = "#22c55e"
    elif status == "resolved":
        status_text = "RESOLVIDO"
        status_color = "#60a5fa"
    elif status == "cancelled":
        status_text = "CANCELADO"
        status_color = "#f97316"
    else:
        status_text = status.upper() if status else "—"
        status_color = "#ef4444"

    rem_color = "#ef4444" if urgent else "rgba(255,255,255,0.60)"

    return f"""<div style=\"display:flex;justify-content:space-between;align-items:center;gap:12px;\">
      <div style=\"color:rgba(255,255,255,0.95);font-weight:650;line-height:1.15;\">{title}</div>
      <div style=\"display:flex;align-items:center;gap:10px;white-space:nowrap;\">
        <span style=\"color:{status_color};font-weight:800;letter-spacing:0.02em;\">{status_text}</span>
        <span style=\"color:{rem_color};font-size:13px;font-weight:600;\">{('Fecha em ' + remaining) if status=='open' else remaining}</span>
      </div>
    </div>"""


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (part / total) * 100.0

def _set_expanded(market_id: str, value: bool = True):
    st.session_state[f"mkt_exp_{market_id}"] = value


def _toast_html(msg: str, kind: str = "success") -> str:
    bg = "rgba(34,197,94,0.22)" if kind == "success" else "rgba(239,68,68,0.18)"
    border = "rgba(34,197,94,0.45)" if kind == "success" else "rgba(239,68,68,0.40)"
    icon = "✅" if kind == "success" else "❌"
    return f"""<style>
  .bet-toast-inline {{
    width: 100%;
    margin: 8px 0 12px 0;
    padding: 12px 14px;
    border-radius: 14px;
    background: {bg};
    border: 1px solid {border};
    color: rgba(255,255,255,0.92);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    box-shadow: 0 16px 40px rgba(0,0,0,0.20);
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    animation: slideInY 240ms ease-out;
  }}
  @keyframes slideInY {{
    from {{ transform: translateY(10px); opacity: 0; }}
    to   {{ transform: translateY(0); opacity: 1; }}
  }}
</style>
<div class="bet-toast-inline"><b>{icon}</b> {msg}</div>
"""


def _flash_render():
    """Mostra um toast uma vez (após rerun) no topo da tab."""
    payload = st.session_state.get("bet_flash")
    if not payload:
        return
    kind = payload.get("kind", "success")
    msg = str(payload.get("msg", ""))

    # 1) Toast nativo (aparece sempre; bom no mobile)
    try:
        st.toast(msg, icon="✅" if kind == "success" else "❌")
    except Exception:
        pass

    # 2) Slide-in inline (visual)
    components.html(_toast_html(msg, kind), height=72)

    st.session_state.pop("bet_flash", None)


def render_betting():


    st.title("Apostas do 60")

    u = current_user()
    admin_enabled = is_admin()

    # -------------------------------------------------
    # AUTH (sem login)
    # -------------------------------------------------
    if not u:
        c1, c2 = st.columns(2)
        with c1:
            login_form()
        with c2:
            signup_form()

        st.divider()
        st.caption("Sem dinheiro real. Moeda virtual com saldo e histórico.")

        # ✅ Admin bootstrap escondido para não-admin
        if admin_enabled:
            with st.expander("Admin (bootstrap) — gerir utilizadores", expanded=False):
                st.caption("Só visível em modo Admin global.")
                invite = (st.secrets.get("BETTING_INVITE_CODE") or "").strip()
                st.markdown("**Invite code (para partilhar):**")
                st.code(invite or "(BETTING_INVITE_CODE não definido)", language="text")
                st.divider()
                admin_panel_create_user()
                admin_panel_disable_user()
                admin_panel_list_users()

        return

    # -------------------------------------------------
    # HEADER (user logged-in)
    # -------------------------------------------------
    colA, colB, colC = st.columns([2, 1, 1])
    with colA:
        st.write(f"👤 **{u['display_name']}**")
    with colB:
        bal = get_balance(u["user_id"])
        st.metric("Saldo", f"{bal:,}".replace(",", " "))
    with colC:
        if st.button("Sair"):
            logout()
            st.rerun()

    # Tabs (Admin só aparece se estiver em modo admin global)
    tab_names = ["Apostas", "Carteira"] + (["Admin"] if admin_enabled else [])
    tabs = st.tabs(tab_names)

    # -----------------
    # Mercados
    # -----------------
    with tabs[0]:
        # Flash message (mostra após rerun)
        _flash_render()
        # Auto-refresh para countdown (a cada 30s) sem fazer hard-reload (mantém login)
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=30_000, key="mkt_autorefresh")
        except Exception:
            # Se a lib não estiver instalada, não forçamos refresh automático
            pass

        show_all = st.toggle("Mostrar resolvidos / histórico", value=False, key="mkt_show_all")
        markets_all = list_markets(limit=200)

        if show_all:
            markets = markets_all
        else:
            markets = [mm for mm in markets_all if mm.get("status") == "open"]

        if not markets:
            st.info("Ainda não há mercados para mostrar.")
        else:
            for m in markets:
                status = (m.get("status") or "").upper()  # usado em alguns sítios de debug
                title = m.get("title", "(sem título)")
                close_time = m.get("close_time")
                close_str = close_time.isoformat() if close_time else "—"

                st.markdown(_market_header_html(title, m.get("status") or "", close_time), unsafe_allow_html=True)
                st.caption(f"ID: `{m.get('market_id','')}`")
                with st.expander("Ver detalhes", expanded=bool(st.session_state.get(f"mkt_exp_{m['market_id']}", False))):

                        st.write(m.get("description", ""))

                        options = m.get("options") or []
                        totals = m.get("totals") or {}
                        total_pool = int(m.get("total_pool") or 0)

                        st.write("**Pote total:**", f"{total_pool:,}".replace(",", " "))

                        # Polymarket-style: percentagens por opção
                        for opt in options:
                            amt_opt = int(totals.get(opt) or 0)
                            pct = _pct(amt_opt, total_pool)
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.write(f"**{opt}** — {pct:0.1f}%")
                                st.progress(min(max(pct / 100.0, 0.0), 1.0))
                            with c2:
                                st.write(f"{amt_opt:,}".replace(",", " "))

                        if (m.get("status") == "open") and options:
                            opt_sel = st.selectbox("Escolhe opção", options, key=f"opt_{m['market_id']}", on_change=_set_expanded, args=(m['market_id'], True))
                            amt = st.number_input("Valor", min_value=1, step=10, value=100, key=f"amt_{m['market_id']}", on_change=_set_expanded, args=(m['market_id'], True))
                            toast_spot = st.empty()
                            if st.button("Apostar", key=f"bet_{m['market_id']}", type="primary"):
                                ok, msg = place_bet(m["market_id"], u["user_id"], opt_sel, int(amt))

                                if ok:
                                    shown_amt = f"{int(amt):,}".replace(",", " ")
                                    nice_msg = f"Aposta submetida com sucesso ({shown_amt})"
                                    # Toast inline exatamente onde o user está (dentro do expander)
                                    toast_spot.markdown(_toast_html(nice_msg, "success"), unsafe_allow_html=True)
                                    # Confetti
                                    try:
                                        st.balloons()
                                    except Exception:
                                        pass
                                    # Som (nota: no iOS pode ser bloqueado; em desktop normalmente toca)
                                    click_wav_b64 = "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="
                                    toast_spot.markdown(f'<audio autoplay><source src="data:audio/wav;base64,{click_wav_b64}" type="audio/wav"></audio>', unsafe_allow_html=True)
                                    # Também guardar para aparecer no topo após rerun (fallback)
                                    st.session_state["bet_flash"] = {"kind": "success", "msg": "✅ " + nice_msg}
                                else:
                                    toast_spot.markdown(_toast_html(str(msg), "error"), unsafe_allow_html=True)
                                    st.session_state["bet_flash"] = {"kind": "error", "msg": "❌ " + str(msg)}

                                # pequeno delay para deixar o browser iniciar o áudio/mostrar toast
                                st.session_state[f"mkt_exp_{m['market_id']}"] = False
                            time.sleep(0.6)
                                st.rerun()
                        else:
                            ro = m.get("resolved_option")
                            if ro:
                                st.success(f"Resolvido: **{ro}**")

    # -----------------
    # Carteira
    # -----------------
    with tabs[1]:
        st.subheader("Histórico (últimas 50)")
        ledger = list_ledger(u["user_id"], limit=50)
        if not ledger:
            st.info("Sem movimentos.")
        else:
            for tx in ledger:
                ts = tx.get("ts")
                kind = tx.get("kind")
                amt = int(tx.get("amount") or 0)
                ref = tx.get("ref")
                st.write(f"- {ts}: **{kind}** {amt:,}".replace(",", " "), f"· ref: {ref}")

    # -----------------
    # Admin (apenas se admin_enabled)
    # -----------------
    if admin_enabled:
        with tabs[2]:
            st.subheader("Admin")
            st.caption("Só visível em modo Admin global.")

            # Mostrar invite code
            invite = (st.secrets.get("BETTING_INVITE_CODE") or "").strip()
            st.markdown("### Invite code (para partilhar)")
            st.code(invite or "(BETTING_INVITE_CODE não definido)", language="text")

            st.divider()
            st.markdown("### Utilizadores")
            admin_panel_create_user()
            admin_panel_disable_user()
            admin_panel_list_users()

            st.divider()
            st.markdown("### Criar mercado")
            title = st.text_input("Título", key="mkt_title")
            desc = st.text_area("Descrição", key="mkt_desc")
            opts_raw = st.text_input("Opções (separadas por ;)", value="SIM;NÃO", key="mkt_opts")
            days = st.number_input("Fecha em (dias)", min_value=0, max_value=30, value=2, step=1, key="mkt_days")
            hour = st.number_input("Hora UTC de fecho", min_value=0, max_value=23, value=20, step=1, key="mkt_hour")

            if st.button("Criar mercado", type="primary"):
                options = [o.strip() for o in (opts_raw or "").split(";") if o.strip()]
                if len(options) < 2:
                    st.error("Mínimo 2 opções.")
                elif not title.strip():
                    st.error("Título obrigatório.")
                else:
                    close_time = _parse_close_time(int(days), int(hour))
                    market_id = create_market(title, desc, options, close_time)
                    st.success(f"Criado: {market_id}")
                    st.rerun()

            st.divider()
            st.markdown("### Resolver / cancelar mercado")

            all_markets = list_markets(limit=200)
            candidates = [m for m in all_markets if m.get("status") in ("open", "closed")]

            if not candidates:
                st.info("Não há mercados pendentes (abertos/por resolver).")
            else:
                def _label(m):
                    title2 = m.get("title", "(sem título)")
                    status2 = (m.get("status") or "").upper()
                    mid2 = m.get("market_id") or ""
                    return f"{title2} · {status2} · {mid2}"

                labels = [_label(m) for m in candidates]
                sel_label = st.selectbox("Escolhe o mercado", labels, key="admin_market_pick")
                sel_idx = labels.index(sel_label)
                market_id = candidates[sel_idx].get("market_id")

                m = get_market(market_id) if market_id else None
                if not m:
                    st.error("Não consegui carregar o mercado selecionado.")
                else:
                    st.write("**ID:**", f"`{market_id}`")
                    st.write("**Título:**", m.get("title"))
                    st.write("**Status:**", m.get("status"))
                    options = m.get("options") or []
                    if not options:
                        st.error("Mercado sem opções.")
                    else:
                        win = st.selectbox("Opção vencedora", options, key="admin_win_opt")

                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("Resolver e pagar", type="primary"):
                                ok, msg = resolve_market(market_id, win)
                                (st.success if ok else st.error)(msg)
                                st.rerun()
                        with c2:
                            if st.button("Cancelar e devolver", type="secondary"):
                                ok, msg = cancel_market(market_id)
                                (st.success if ok else st.error)(msg)
                                st.rerun()

            st.divider()
            st.markdown("### Apagar mercado")
            st.caption("Apaga mercados resolvidos/cancelados (inclui as apostas desse mercado).")

            db = fs_client()
            all_for_delete = list_markets(limit=300)
            deletable = [mm for mm in all_for_delete if mm.get("status") in ("resolved", "cancelled")]

            if not deletable:
                st.info("Não há mercados resolvidos/cancelados para apagar.")
            else:
                def _dlabel(m):
                    title3 = m.get("title", "(sem título)")
                    status3 = (m.get("status") or "").upper()
                    mid3 = m.get("market_id") or ""
                    return f"{title3} · {status3} · {mid3}"

                dlabels = [_dlabel(mm) for mm in deletable]
                dsel = st.selectbox("Escolhe o mercado para apagar", dlabels, key="admin_market_delete_pick")
                didx = dlabels.index(dsel)
                del_market_id = deletable[didx].get("market_id")

                st.warning("Isto remove o mercado e as bets associadas. Não dá para desfazer.")
                confirm = st.checkbox("Confirmo que quero apagar este mercado", key="admin_market_delete_confirm")

                if st.button("Apagar mercado", type="primary", disabled=not confirm, key="admin_market_delete_btn"):
                    mref = db.collection("markets").document(del_market_id)

                    # apagar bets em batches
                    bets = list(mref.collection("bets").stream())
                    batch = db.batch()
                    ops = 0
                    for bdoc in bets:
                        batch.delete(bdoc.reference)
                        ops += 1
                        if ops >= 450:
                            batch.commit()
                            batch = db.batch()
                            ops = 0
                    if ops:
                        batch.commit()

                    # apagar mercado
                    mref.delete()

                    st.success(f"Mercado apagado: {del_market_id}")
                    st.rerun()
