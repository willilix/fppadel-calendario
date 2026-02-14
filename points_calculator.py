import streamlit as st

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
    """Formato PT: separador decimal vírgula e milhares com ponto."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calcular_pontos(nivel: int, classe: int, posicao: str) -> float:
    base = BASE_POINTS_50K_QUADRO_A[posicao]
    m_classe = CLASS_MULTIPLIER[classe]
    m_nivel = LEVEL_MULTIPLIER[nivel]
    return base * m_classe * m_nivel


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

    # ✅ Nota única, com parágrafos entre linhas
    st.info(
        "- M1 os primeiros 100 no ranking\n\n"
        "- M2 do 101 ao 250\n\n"
        "- M3 do 251 ao 500\n\n"
        "- M4 do 501 ao 750\n\n"
        "- M5 do 751 ao 1000\n\n"
        "- M6 do 1001 até ao último looser\n\n"
        "- F1 os primeiros 100 no ranking\n\n"
        "- F2 do 101 ao 150\n\n"
        "- F3 do 151 ao 300\n\n"
        "- F4 do 301 ao 450\n\n"
        "- F5 do 451 ao 600\n\n"
        "- F6 do 601 até à última looser"
    )


# Se quiseres testar este ficheiro isoladamente:
if __name__ == "__main__":
    st.set_page_config(page_title="Calculadora de Pontos", layout="centered")
    render_points_calculator()

