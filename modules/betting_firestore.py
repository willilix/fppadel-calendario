import datetime as dt
from typing import Optional, Dict, Any, List, Tuple

import streamlit as st
from google.cloud import firestore
from google.oauth2.service_account import Credentials

# Collections:
# users/{user_id}
# wallets/{user_id}/ledger/{tx_id}
# markets/{market_id}
# markets/{market_id}/bets/{bet_id}

@st.cache_resource
def fs_client():
    sa_info = dict(st.secrets["GCP_SERVICE_ACCOUNT"])
    pk = sa_info.get("private_key", "")
    if "\\n" in pk:
        sa_info["private_key"] = pk.replace("\\n", "\n")

    creds = Credentials.from_service_account_info(sa_info)
    project_id = st.secrets.get("FIRESTORE_PROJECT_ID") or sa_info.get("project_id")

    return firestore.Client(project=project_id, credentials=creds)

def now_utc():
    return dt.datetime.now(dt.timezone.utc)

def _doc_id(prefix: str) -> str:
    # Firestore auto-id é ok, mas às vezes queremos id previsível; aqui fica simples:
    return f"{prefix}_{int(now_utc().timestamp()*1000)}"

# --------------------
# Users & Wallet
# --------------------

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    doc = fs_client().collection("users").document(user_id).get()
    return doc.to_dict() if doc.exists else None

def create_user(user_id: str, display_name: str, pin_hash: str, initial_balance: int = 10_000) -> None:
    db = fs_client()
    uref = db.collection("users").document(user_id)
    wref = db.collection("wallets").document(user_id)

    batch = db.batch()
    batch.set(uref, {
        "user_id": user_id,
        "display_name": display_name,
        "pin_hash": pin_hash,
        "is_disabled": False,
        "created_at": now_utc(),
    })
    batch.set(wref, {
        "user_id": user_id,
        "balance": int(initial_balance),
        "updated_at": now_utc(),
    })
    batch.commit()

    add_ledger(user_id, kind="credit", amount=int(initial_balance), ref="initial_grant", meta={"note": "Saldo inicial"})

def set_user_disabled(user_id: str, disabled: bool) -> None:
    fs_client().collection("users").document(user_id).set({"is_disabled": bool(disabled)}, merge=True)

def get_balance(user_id: str) -> int:
    doc = fs_client().collection("wallets").document(user_id).get()
    if not doc.exists:
        return 0
    return int((doc.to_dict() or {}).get("balance") or 0)

def add_ledger(user_id: str, kind: str, amount: int, ref: str, meta: Optional[dict] = None):
    db = fs_client()
    tx_id = _doc_id("tx")
    db.collection("wallets").document(user_id).collection("ledger").document(tx_id).set({
        "ts": now_utc(),
        "kind": kind,          # credit/debit/payout/refund
        "amount": int(amount), # sempre positivo aqui
        "ref": ref,            # market_id, etc
        "meta": meta or {},
    })

def list_ledger(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    db = fs_client()
    q = (db.collection("wallets").document(user_id).collection("ledger")
         .order_by("ts", direction=firestore.Query.DESCENDING)
         .limit(limit))
    return [d.to_dict() for d in q.stream()]

# --------------------
# Markets
# --------------------

def create_market(title: str, description: str, options: List[str], close_time: dt.datetime) -> str:
    db = fs_client()
    market_id = _doc_id("mkt")
    db.collection("markets").document(market_id).set({
        "market_id": market_id,
        "title": title.strip(),
        "description": description.strip(),
        "options": options,
        "status": "open",  # open/closed/resolved/cancelled
        "close_time": close_time,
        "created_at": now_utc(),
        "resolved_at": None,
        "resolved_option": None,
        "totals": {opt: 0 for opt in options},
        "total_pool": 0,
    })
    return market_id

def list_markets(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    db = fs_client()
    q = db.collection("markets").order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
    if status:
        q = q.where("status", "==", status)
    return [d.to_dict() for d in q.stream()]

def get_market(market_id: str) -> Optional[Dict[str, Any]]:
    doc = fs_client().collection("markets").document(market_id).get()
    return doc.to_dict() if doc.exists else None

# --------------------
# Betting (Parimutuel)
# --------------------

def place_bet(market_id: str, user_id: str, option: str, amount: int) -> Tuple[bool, str]:
    """
    Parimutuel: só registamos apostas e actualizamos totais.
    Debita a wallet do user numa transaction.
    """
    if amount <= 0:
        return False, "Valor inválido."

    db = fs_client()
    mref = db.collection("markets").document(market_id)
    wref = db.collection("wallets").document(user_id)
    bref = mref.collection("bets").document(_doc_id("bet"))

    @firestore.transactional
    def _tx(tx: firestore.Transaction):
        mdoc = mref.get(transaction=tx)
        if not mdoc.exists:
            raise ValueError("Mercado não existe.")
        m = mdoc.to_dict() or {}

        if m.get("status") != "open":
            raise ValueError("Mercado não está aberto.")

        close_time = m.get("close_time")
        if close_time and now_utc() >= close_time:
            raise ValueError("Mercado já fechou.")

        if option not in (m.get("options") or []):
            raise ValueError("Opção inválida.")

        wdoc = wref.get(transaction=tx)
        if not wdoc.exists:
            raise ValueError("Carteira não existe.")
        w = wdoc.to_dict() or {}
        bal = int(w.get("balance") or 0)
        if bal < amount:
            raise ValueError("Saldo insuficiente.")

        # debit wallet
        tx.update(wref, {"balance": bal - amount, "updated_at": now_utc()})

        # bet record
        tx.set(bref, {
            "bet_id": bref.id,
            "user_id": user_id,
            "option": option,
            "amount": int(amount),
            "ts": now_utc(),
        })

        # update totals
        totals = dict(m.get("totals") or {})
        totals[option] = int(totals.get(option) or 0) + int(amount)
        total_pool = int(m.get("total_pool") or 0) + int(amount)
        tx.update(mref, {"totals": totals, "total_pool": total_pool})

    try:
        tx = db.transaction()
        _tx(tx)
        add_ledger(user_id, kind="debit", amount=int(amount), ref=market_id, meta={"option": option})
        return True, "Aposta feita."
    except Exception as e:
        return False, str(e)

def resolve_market(market_id: str, winning_option: str) -> Tuple[bool, str]:
    """
    Paga vencedores proporcionalmente:
      payout_user = floor(user_win_amount / total_win_pool * total_pool)
    (podes deixar uma pequena taxa/house cut no futuro, aqui é 0)
    """
    db = fs_client()
    mref = db.collection("markets").document(market_id)

    m = get_market(market_id)
    if not m:
        return False, "Mercado não existe."

    if m.get("status") in ("resolved", "cancelled"):
        return False, "Mercado já está fechado."

    options = m.get("options") or []
    if winning_option not in options:
        return False, "Opção vencedora inválida."

    totals = m.get("totals") or {}
    total_pool = int(m.get("total_pool") or 0)
    win_pool = int(totals.get(winning_option) or 0)

    # se ninguém apostou na opção vencedora: devolvemos (refund) a todos
    # (mais justo do que “casa fica com tudo” num sistema play-money)
    bets = list(mref.collection("bets").stream())
    bet_docs = [b.to_dict() for b in bets]

    try:
        batch = db.batch()

        if win_pool <= 0:
            # refund todos
            for b in bet_docs:
                uid = b["user_id"]
                amt = int(b["amount"])
                wref = db.collection("wallets").document(uid)
                # increment balance
                batch.update(wref, {"balance": firestore.Increment(amt), "updated_at": now_utc()})
                add_ledger(uid, kind="refund", amount=amt, ref=market_id, meta={"reason": "no_winners"})
            status = "resolved"
        else:
            # payouts vencedores proporcional
            for b in bet_docs:
                if b.get("option") != winning_option:
                    continue
                uid = b["user_id"]
                user_win_amt = int(b["amount"])
                payout = int((user_win_amt / win_pool) * total_pool)
                if payout <= 0:
                    continue
                wref = db.collection("wallets").document(uid)
                batch.update(wref, {"balance": firestore.Increment(payout), "updated_at": now_utc()})
                add_ledger(uid, kind="payout", amount=payout, ref=market_id, meta={"option": winning_option})

            status = "resolved"

        batch.update(mref, {
            "status": status,
            "resolved_at": now_utc(),
            "resolved_option": winning_option,
        })
        batch.commit()
        return True, "Mercado resolvido e payouts feitos."
    except Exception as e:
        return False, str(e)

def cancel_market(market_id: str) -> Tuple[bool, str]:
    """Cancela e devolve todas as apostas."""
    db = fs_client()
    mref = db.collection("markets").document(market_id)
    m = get_market(market_id)
    if not m:
        return False, "Mercado não existe."
    if m.get("status") in ("resolved", "cancelled"):
        return False, "Mercado já fechado."

    bets = list(mref.collection("bets").stream())
    bet_docs = [b.to_dict() for b in bets]

    try:
        batch = db.batch()
        for b in bet_docs:
            uid = b["user_id"]
            amt = int(b["amount"])
            wref = db.collection("wallets").document(uid)
            batch.update(wref, {"balance": firestore.Increment(amt), "updated_at": now_utc()})
            add_ledger(uid, kind="refund", amount=amt, ref=market_id, meta={"reason": "cancelled"})
        batch.update(mref, {"status": "cancelled", "resolved_at": now_utc(), "resolved_option": None})
        batch.commit()
        return True, "Mercado cancelado e apostas devolvidas."
    except Exception as e:
        return False, str(e)
