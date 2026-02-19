import streamlit as st

ADMIN_SESSION_KEY = "is_admin"

def is_admin() -> bool:
    return bool(st.session_state.get(ADMIN_SESSION_KEY, False))

def admin_logout():
    st.session_state[ADMIN_SESSION_KEY] = False

def admin_login_form(label="Admin PIN"):
    pin = st.text_input(label, type="password", key="global_admin_pin")
    if st.button("Entrar (Admin)", type="primary", use_container_width=True):
        if pin == (st.secrets.get("BETTING_ADMIN_PIN") or ""):
            st.session_state[ADMIN_SESSION_KEY] = True
            st.success("Admin desbloqueado.")
            st.rerun()
        else:
            st.error("PIN inválido.")

def admin_top_button():
    # mete isto no topo da app (ex.: na sidebar ou header area)
    col1, col2 = st.columns([1, 1])
    with col1:
        if is_admin():
            st.success("Admin: ON")
        else:
            st.caption("Admin: OFF")
    with col2:
        if is_admin():
            if st.button("Sair Admin", use_container_width=True):
                admin_logout()
                st.rerun()
        else:
            with st.popover("🔒 Admin", use_container_width=True):
                admin_login_form()
