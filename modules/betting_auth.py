import os
import base64
import hashlib
import hmac
import re
import streamlit as st

from modules.betting_firestore import get_user, create_user, set_user_disabled

from modules.betting_firestore import fs_client, get_balance

def _slug_user_id(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9_-]+", "_", name)
    return name[:40] or "user"

def hash_pin(pin: str, salt_b64: str = None) -> str:
    pin = (pin or "").strip()
    if not salt_b64:
        salt = os.urandom(16)
        salt_b64 = base64.b64encode(salt).decode("utf-8")
    else:
        salt = base64.b64decode(salt_b64.encode("utf-8"))

    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 150_000, dklen=32)
    dk_b64 = base64.b64encode(dk).decode("utf-8")
    return f"pbkdf2_sha256$150000${salt_b64}${dk_b64}"

def verify_pin(pin: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calc = hash_pin(pin, salt_b64=salt_b64)
        return hmac.compare_digest(calc, stored)
    except Exception:
        return False

def current_user():
    return st.session_state.get("bet_user")

def logout():
    st.session_state.pop("bet_user", None)

def login_form():
    st.subheader("Login")
    name = st.text_input("Nome", key="bet_login_name")
    pin = st.text_input("PIN", type="password", key="bet_login_pin")
    if st.button("Entrar", use_container_width=True):
        user_id = _slug_user_id(name)
        u = get_user(user_id)
        if not u:
            st.error("Utilizador não existe. Pede ao admin para te criar.")
            return
        if u.get("is_disabled"):
            st.error("Conta desativada.")
            return
        if not verify_pin(pin, u.get("pin_hash","")):
            st.error("PIN errado.")
            return
        st.session_state["bet_user"] = {"user_id": user_id, "display_name": u.get("display_name") or name}
        st.success("Login feito.")
        st.rerun()

def admin_panel_create_user():
    st.markdown("### Admin: criar utilizador")
    admin_pin = st.text_input("Admin PIN", type="password", key="bet_admin_pin")
    if admin_pin != (st.secrets.get("BETTING_ADMIN_PIN") or ""):
        st.info("Introduz o Admin PIN para gerir utilizadores.")
        return

    display_name = st.text_input("Nome do utilizador (display)")
    pin = st.text_input("PIN do utilizador", type="password")
    initial = st.number_input("Saldo inicial", min_value=0, max_value=1_000_000, value=10_000, step=1000)

    if st.button("Criar utilizador", type="primary"):
        user_id = _slug_user_id(display_name)
        u = get_user(user_id)
        if u:
            st.error("Já existe um utilizador com este nome (id).")
            return
        if not pin or len(pin) < 4:
            st.error("PIN demasiado curto (mínimo 4).")
            return
        pin_hash = hash_pin(pin)
        create_user(user_id=user_id, display_name=display_name, pin_hash=pin_hash, initial_balance=int(initial))
        st.success(f"Utilizador criado: {display_name} (id: {user_id})")

def admin_panel_disable_user():
    st.markdown("### Admin: desativar / reativar utilizador")
    admin_pin = st.text_input("Admin PIN (gestão)", type="password", key="bet_admin_pin2")
    if admin_pin != (st.secrets.get("BETTING_ADMIN_PIN") or ""):
        return

    user_id = st.text_input("user_id (slug)", placeholder="ex: joao_silva")
    disabled = st.toggle("Desativado", value=False)
    if st.button("Aplicar", key="bet_disable_apply"):
        set_user_disabled(user_id, disabled)
        st.success("Atualizado.")

def admin_panel_list_users():
    st.markdown("### Admin: listar utilizadores")

    admin_pin = st.text_input("Admin PIN (listar)", type="password", key="bet_admin_pin_list")
    if admin_pin != (st.secrets.get("BETTING_ADMIN_PIN") or ""):
        return

    db = fs_client()
    users = list(db.collection("users").stream())

    if not users:
        st.info("Sem utilizadores.")
        return

    for u in users:
        data = u.to_dict()
        uid = data.get("user_id")
        bal = get_balance(uid)
        disabled = data.get("is_disabled")

        col1, col2, col3 = st.columns([3,1,1])
        with col1:
            st.write(f"**{data.get('display_name')}** ({uid})")
        with col2:
            st.write(f"Saldo: {bal}")
        with col3:
            if st.button("Apagar", key=f"del_{uid}"):
                db.collection("users").document(uid).delete()
                db.collection("wallets").document(uid).delete()
                st.success(f"{uid} apagado.")
                st.rerun()
