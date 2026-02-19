import streamlit as st

ADMIN_SESSION_KEY = "is_admin_global"


def is_admin() -> bool:
    return bool(st.session_state.get(ADMIN_SESSION_KEY, False))


def admin_logout():
    st.session_state[ADMIN_SESSION_KEY] = False


def _admin_login(pin: str) -> bool:
    expected = (st.secrets.get("BETTING_ADMIN_PIN") or "").strip()
    return bool(expected) and (pin == expected)


def admin_top_button():
    """
    Botão fixo no topo direito (por cima do logo) com estado ON/OFF.
    """
    # CSS: fixo no topo direito
    st.markdown(
        """
        <style>
        .admin-fixed {
            position: fixed;
            top: 14px;
            right: 18px;
            z-index: 99999;
            display: flex;
            gap: 10px;
            align-items: center;
            padding: 8px 10px;
            border-radius: 14px;
            background: rgba(20,20,20,0.55);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.12);
        }
        .admin-pill {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.18);
            color: rgba(255,255,255,0.9);
            line-height: 1;
            white-space: nowrap;
        }
        .admin-pill.on { background: rgba(34,197,94,0.22); }
        .admin-pill.off { background: rgba(239,68,68,0.18); }

        /* manter o wrapper no topo mesmo com header do streamlit */
        @media (max-width: 640px) {
            .admin-fixed { right: 10px; top: 10px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # “âncora” HTML para posicionar; os widgets vêm logo a seguir
    st.markdown(
        f"""
        <div class="admin-fixed">
          <div class="admin-pill {'on' if is_admin() else 'off'}">
            {'Admin: ON' if is_admin() else 'Admin: OFF'}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Colocar os widgets “por cima” usando um container vazio (Streamlit não permite button dentro do HTML)
    # Trick: usar um container e empurrar com CSS para o mesmo sítio.
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"] > div:has(> div.admin-widget-anchor){
            position: fixed;
            top: 14px;
            right: 18px;
            z-index: 100000;
        }
        .admin-widget-anchor { display: inline-block; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="admin-widget-anchor"></div>', unsafe_allow_html=True)

        if is_admin():
            # botão sair
            if st.button("Sair", key="admin_fixed_logout"):
                admin_logout()
                st.rerun()
        else:
            # popover login
            with st.popover("🔒 Admin", use_container_width=False):
                pin = st.text_input("Admin PIN", type="password", key="admin_fixed_pin")
                if st.button("Entrar", type="primary", key="admin_fixed_login"):
                    if _admin_login(pin):
                        st.session_state[ADMIN_SESSION_KEY] = True
                        st.success("Admin ligado.")
                        st.rerun()
                    else:
                        st.error("PIN inválido.")
