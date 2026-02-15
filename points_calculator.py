import streamlit as st
import requests
import uuid

# ----------------------------
# Config (tabela do anexo)
# ----------------------------
BASE_POINTS_50K_QUADRO_A = {
    "Vencedor": 50000,
    "Finalista": 35000,
    "3º lugar": 27500,
    "4º lugar": 27500,
    "1/4 final": 21250,
    "1/8 final": 16250,
    "1/16 final": 11250,
}

CLASS_MULTIPLIER = {
    50000: 1.00,
    25000: 0.50,
    10000: 0.20,
    5000: 0.10,
    2000: 0.04,
}

LEVEL_MULTIPLIER = {
    2: 0.35,
    3: 0.1225,
    4: 0.042875,
    5: 0.015,
    6: 0.00525,
}


def _fmt_pt(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calcular_pontos(nivel: int, classe: int, posicao: str) -> float:
    base = BASE_POINTS_50K_QUADRO_A[posicao]
    m_classe = CLASS_MULTIPLIER[classe]
    m_nivel = LEVEL_MULTIPLIER[nivel]
    return base * m_classe * m_nivel


# ----------------------------
# GA4 SERVER-SIDE EVENT
# ----------------------------
def send_ga_event(event_name: str, params: dict):
    measurement_id = st.secrets.get("GA_MEASUREMENT_ID")
    api_secret = st.secrets.get("GA_API_SECRET")

    if not measurement_id or not api_secret:
        return

    if "_ga_client_id" not in st.session_state:
        st.session_state["_ga_client_id"] = f"{uuid.uuid4()}.{uuid.uuid4()}"

    payload = {
        "client_id": st.session_state["_ga_client_id"],
        "events": [
            {
                "name": event_name,
                "params": params,
            }
        ],
    }

    url = f"https://www.google-analytics.com/mp/collect?measurement_id={measurement_id}&api_secret={api_secret}"

    try:
        requests.post(url, json=payload, timeout=3)
    except Exception:
        pass


def render_points_calculator():
    st.subheader("Calculadora de Pontos (FPPadel – Absolutos)")
    st.caption("Baseado na coluna “Quadro A” (classe 50.000) + multiplicadores de classe e nível.")

    col1, col2, col3 = st.columns(3)

    with col1:
        nivel = st.selectbox("Nível", options=[2, 3, 4, 5, 6], index=0)

    with col2:
        classe = st.selectbox("Classe do torneio", options=[50000, 25000, 10000, 5000, 2000], index=0)

    with col3:
        posicao = st.selectbox("Posição final", options=list(BASE_POINTS_50K_QUADRO_A.keys()), index=0)

    # --- TRACKING (1 vez por sessão)
    signature = f"{nivel}|{classe}|{posicao}"
    prev = st.session_state.get("_pc_signature")

    if prev and signature != prev and not st.session_state.get("_pc_sent"):
        st.session_state["_pc_sent"] = True
        send_ga_event(
            "points_calculator_used",
            {
                "nivel": nivel,
                "classe": classe,
                "posicao": posicao,
            },
        )

    st.session_state["_pc_signature"] = signature

    pontos = calcular_pontos(nivel=nivel, classe=classe, posicao=posicao)

    base = BASE_POINTS_50K_QUADRO_A[posicao]
    m_classe = CLASS_MULTIPLIER[classe]
    m_nivel = LEVEL_MULTIPLIER[nivel]

    st.markdown("---")
    st.metric("Pontos ganhos", _fmt_pt(pontos))

    with st.expander("Ver detalhe do cálculo", expanded=False):
        st.write(f"**Base (50.000 / Quadro A)** para *{posicao}*: `{base}`")
        st.write(f"**Multiplicador da classe {classe}**: `{m_classe}`")
        st.write(f"**Multiplicador do nível {nivel}**: `{m_nivel}`")
        st.write(f"**Fórmula**: `{base} × {m_classe} × {m_nivel} = {_fmt_pt(pontos)}`")

    st.markdown("Calculadora pronta.", unsafe_allow_html=True)


if __name__ == "__main__":
    st.set_page_config(page_title="Calculadora de Pontos", layout="centered")
    render_points_calculator()
