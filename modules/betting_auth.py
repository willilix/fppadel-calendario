import os
import base64
import hashlib
import hmac
import re
import streamlit as st

from modules.betting_firestore import get_user, create_user, set_user_disabled, fs_client, get_balance


def _slug_user_id(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9_-]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:40] or "user"


def hash_pin(pin: str, salt_b64: str | None = None) -> str:
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
        algo, _iters, salt_b64, _dk_b64 = stored.split("$", 3)
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
    if st.button("Entrar", use_container_width=True, key="bet_login_btn"):
        user_id = _slug_user_id(name)
        u = get_user(user_id)
        if not u:
            st.error("Utilizador não existe. Cria conta (registo) ou pede ao admin.")
            return
        if u.get("is_disabled"):
            st.error("Conta desativada.")
            return
        if not verify_pin(pin, u.get("pin_hash", "")):
            st.error("PIN errado.")
            return
        st.session_state["bet_user"] = {"user_id": user_id, "display_name": u.get("display_name") or name}
        st.success("Login feito.")
        st.rerun()


def signup_form():
    """Auto-registo simples com código de convite global."""
    st.subheader("Criar conta")
    invite_expected = (st.secrets.get("BETTING_INVITE_CODE") or "").strip()
    initial_balance = int(st.secrets.get("BETTING_INITIAL_BALANCE") or 10_000)

    if not invite_expected:
        st.warning("Auto-registo indisponível: define BETTING_INVITE_CODE nos Secrets.")
        return

    display_name = st.text_input("Nome", key="bet_signup_name")
    pin = st.text_input("PIN (mín. 4)", type="password", key="bet_signup_pin")
    invite = st.text_input("Invite code", type="password", key="bet_signup_invite")

    if st.button("Criar conta", type="primary", use_container_width=True, key="bet_signup_btn"):
        user_id = _slug_user_id(display_name)

        if not display_name.strip():
            st.error("Nome obrigatório.")
            return
        if not pin or len(pin) < 4:
            st.error("PIN demasiado curto (mínimo 4).")
            return
        if invite.strip() != invite_expected:
            st.error("Invite code inválido.")
            return

        u = get_user(user_id)
        if u:
            st.error("Já existe um utilizador com este nome. Experimenta adicionar algo ao nome.")
            return

        pin_hash = hash_pin(pin)
        create_user(user_id=user_id, display_name=display_name.strip(), pin_hash=pin_hash, initial_balance=initial_balance)

        # auto-login
        st.session_state["bet_user"] = {"user_id": user_id, "display_name": display_name.strip()}
        st.success("Conta criada e login feito.")
        st.rerun()


def admin_panel_create_user():
    st.markdown("### Admin: criar utilizador")
    admin_pin = st.text_input("Admin PIN", type="password", key="bet_admin_pin")
    if admin_pin != (st.secrets.get("BETTING_ADMIN_PIN") or ""):
        st.info("Introduz o Admin PIN para gerir utilizadores.")
        return

    display_name = st.text_input("Nome do utilizador (display)", key="bet_admin_create_name")
    pin = st.text_input("PIN do utilizador", type="password", key="bet_admin_create_pin")
    initial = st.number_input("Saldo inicial", min_value=0, max_value=1_000_000, value=10_000, step=1000, key="bet_admin_create_initial")

    if st.button("Criar utilizador", type="primary", key="bet_admin_create_btn"):
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

    user_id = st.text_input("user_id (slug)", placeholder="ex: joao_silva", key="bet_admin_disable_user_id")
    disabled = st.toggle("Desativado", value=False, key="bet_admin_disable_toggle")
    if st.button("Aplicar", key="bet_disable_apply"):
        set_user_disabled(user_id, disabled)
        st.success("Atualizado.")


def admin_panel_list_users():
    st.markdown("### Admin: listar / apagar utilizadores")
    admin_pin = st.text_input("Admin PIN (listar)", type="password", key="bet_admin_pin_list")
    if admin_pin != (st.secrets.get("BETTING_ADMIN_PIN") or ""):
        return

    db = fs_client()
    users = list(db.collection("users").stream())
    if not users:
        st.info("Sem utilizadores.")
        return

    for udoc in users:
        data = udoc.to_dict() or {}
        uid = data.get("user_id") or udoc.id
        bal = get_balance(uid)
        disabled = bool(data.get("is_disabled"))

        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            st.write(f"**{data.get('display_name', uid)}**  ·  `{uid}`")
        with col2:
            st.write(f"{bal:,}".replace(",", " "))
        with col3:
            st.write("🚫" if disabled else "✅")
        with col4:
            if st.button("Apagar", key=f"del_{uid}"):
                # apagar user + wallet (inclui ledger/bets ficam nos mercados, o que é ok)
                db.collection("users").document(uid).delete()
                db.collection("wallets").document(uid).delete()
                st.success(f"Apagado: {uid}")
                st.rerun()
