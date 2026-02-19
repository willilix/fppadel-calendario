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
    st.markdown(
        """
        <style>
        /* O wrapper que contém o nosso marcador */
        div[data-testid="stVerticalBlock"] > div:has(div.admin-fixed-root) {
            position: fixed;
            top: 14px;
            right: 18px;
            left: auto !important;

            /* 👇 evita esticar a largura */
            width: fit-content !important;
            max-width: none !important;

            z-index: 99999;

            display: inline-flex;
            flex-direction: row;
            align-items: center;
            gap: 10px;

            padding: 8px 10px;
            border-radius: 14px;
            background: rgba(20,20,20,0.55);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.12);
        }

        /* Evitar que filhos ocupem 100% */
        div[data-testid="stVerticalBlock"] > div:has(div.admin-fixed-root) > div {
            width: auto !important;
            flex: 0 0 auto !important;
            margin: 0 !important;
            padding: 0 !important;
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

        @media (max-width: 640px) {
            div[data-testid="stVerticalBlock"] > div:has(div.admin-fixed-root) {
                right: 10px;
                top: 10px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        # marcador
        st.markdown('<div class="admin-fixed-root"></div>', unsafe_allow_html=True)

        # estado
        st.markdown(
            f'<div class="admin-pill {"on" if is_admin() else "off"}">'
            f'{"Admin: ON" if is_admin() else "Admin: OFF"}'
            f"</div>",
            unsafe_allow_html=True,
        )

        # botão no mesmo bloco
        if is_admin():
            if st.button("Sair", key="admin_fixed_logout"):
                admin_logout()
                st.rerun()
        else:
            with st.popover("🔒 Admin"):
                pin = st.text_input("Admin PIN", type="password", key="admin_fixed_pin")
                if st.button("Entrar", type="primary", key="admin_fixed_login"):
                    if _admin_login(pin):
                        st.session_state[ADMIN_SESSION_KEY] = True
                        st.rerun()
                    else:
                        st.error("PIN inválido.")
