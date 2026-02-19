import datetime as dt
import streamlit as st

from modules.betting_firestore import (
    list_markets, create_market, place_bet, get_market,
    resolve_market, cancel_market, get_balance, list_ledger
)
from modules.betting_auth import (
    current_user, login_form, signup_form, logout,
    admin_panel_create_user, admin_panel_disable_user, admin_panel_list_users
)


def _parse_close_time(days_ahead: int, hour: int) -> dt.datetime:
    tz = dt.timezone.utc
    now = dt.datetime.now(tz)
    close = (now + dt.timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return close


def render_betting():
    st.title("Mercados (play-money)")

    u = current_user()

    # -------------------------------------------------
    # BOOTSTRAP / AUTH
    # -------------------------------------------------
    if not u:
        c1, c2 = st.columns(2)
        with c1:
            login_form()
        with c2:
            signup_form()

        st.divider()
        with st.expander("Admin (bootstrap) — criar/gerir utilizadores", expanded=False):
            st.caption("Se não quiseres auto-registo, usa esta área para criar contas manualmente.")

            admin_pin_chk = st.text_input("Admin PIN (mostrar invite)", type="password", key="bet_admin_pin_show_invite_boot")
            if admin_pin_chk == (st.secrets.get("BETTING_ADMIN_PIN") or ""):
                invite = (st.secrets.get("BETTING_INVITE_CODE") or "").strip()
                st.markdown("**Invite code (para partilhar):**")
                st.code(invite or "(BETTING_INVITE_CODE não definido)", language="text")
                st.caption("Partilha este código com o grupo para poderem criar conta.")
            else:
                st.caption("Introduz o Admin PIN para mostrar o invite code.")

            st.divider()
            admin_panel_create_user()
            admin_panel_disable_user()
            admin_panel_list_users()
        st.caption("Sem dinheiro real. Moeda virtual com saldo e histórico.")
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

    tabs = st.tabs(["Mercados", "Carteira", "Admin"])

    # -----------------
    # Mercados
    # -----------------
    with tabs[0]:
        markets = list_markets(limit=50)
        if not markets:
            st.info("Ainda não há mercados.")
        else:
            for m in markets:
                status = m.get("status")
                title = m.get("title", "(sem título)")
                close_time = m.get("close_time")
                close_str = close_time.isoformat() if close_time else "—"

                with st.expander(f"{title}  ·  {status.upper()}  ·  fecha: {close_str}", expanded=False):
                    st.caption(f"ID: `{m['market_id']}`")
                    st.write(m.get("description", ""))
                    options = m.get("options") or []
                    totals = m.get("totals") or {}
                    total_pool = int(m.get("total_pool") or 0)

                    st.write("**Pote total:**", f"{total_pool:,}".replace(",", " "))

                    for opt in options:
                        st.write(f"- {opt}: {int(totals.get(opt) or 0):,}".replace(",", " "))

                    if status == "open":
                        opt_sel = st.selectbox("Escolhe opção", options, key=f"opt_{m['market_id']}")
                        amt = st.number_input("Valor", min_value=1, step=10, value=100, key=f"amt_{m['market_id']}")
                        if st.button("Apostar", key=f"bet_{m['market_id']}", type="primary"):
                            ok, msg = place_bet(m["market_id"], u["user_id"], opt_sel, int(amt))
                            (st.success if ok else st.error)(msg)
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
    # Admin
    # -----------------
    with tabs[2]:
        st.subheader("Admin")
        st.caption("Criar mercados, resolver, cancelar, e gerir utilizadores. Protegido por Admin PIN.")

        admin_pin = st.text_input("Admin PIN (mercados)", type="password", key="bet_admin_pin_markets")
        is_admin = admin_pin == (st.secrets.get("BETTING_ADMIN_PIN") or "")

        if is_admin:
            invite = (st.secrets.get("BETTING_INVITE_CODE") or "").strip()
            st.markdown("### Invite code (para partilhar)")
            st.code(invite or "(BETTING_INVITE_CODE não definido)", language="text")

        st.divider()
        admin_panel_create_user()
        admin_panel_disable_user()
        admin_panel_list_users()

        st.divider()
        st.markdown("### Admin: criar mercado")
        if not is_admin:
            st.info("Introduz o Admin PIN para criar/resolver mercados.")
        else:
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
            st.markdown("### Admin: resolver / cancelar mercado")
            market_id = st.text_input("market_id", placeholder="ex: mkt_...", key="admin_market_id")
            if market_id:
                m = get_market(market_id)
                if not m:
                    st.error("Não existe.")
                else:
                    st.write("**Título:**", m.get("title"))
                    st.write("**Status:**", m.get("status"))
                    options = m.get("options") or []
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
