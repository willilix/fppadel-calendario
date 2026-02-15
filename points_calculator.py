import streamlit as st
import streamlit.components.v1 as components

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


def _ga_points_used_event(nivel: int, classe: int, posicao: str):
    """
    Envia evento GA4 no browser com retry até o gtag existir.
    Para DebugView: abrir a app com ?ga_debug=1
    """
    # escapar aspas por segurança
    pos = str(posicao).replace('"', '\\"')

    components.html(
        f"""
        <script>
          (function() {{
            const params = {{
              nivel: {int(nivel)},
              classe: {int(classe)},
              posicao: "{pos}"
            }};

            // DebugView: adicionar ?ga_debug=1 no URL
            const url = new URL(window.location.href);
            if (url.searchParams.get('ga_debug') === '1') {{
              params.debug_mode = true;
            }}

            let tries = 0;
            const maxTries = 24;      // ~6s
            const intervalMs = 250;

            function fire() {{
              try {{
                if (typeof gtag === 'function') {{
                  gtag('event', 'points_calculator_used', params);
                  return true;
                }}
                if (window.parent && typeof window.parent.gtag === 'function') {{
                  window.parent.gtag('event', 'points_calculator_used', params);
                  return true;
                }}
              }} catch(e) {{}}
              return false;
            }}

            const timer = setInterval(() => {{
              tries += 1;
              if (fire() || tries >= maxTries) {{
                clearInterval(timer);
              }}
            }}, intervalMs);

          }})();
        </script>
        """,
        height=0,
    )


def render_points_calculator():
    st.subheader("Calculadora de Pontos (FPPadel – Absolutos)")
    st.caption("Baseado na coluna “Quadro A” (classe 50.000) + multiplicadores de classe e nível.")

    col1, col2, col3 = st.columns(3)

    with col1:
        nivel = st.selectbox("Nível", options=[2, 3, 4, 5, 6], index=0, key="pc_nivel")

    with col2:
        classe = st.selectbox(
            "Classe do torneio",
            options=[50000, 25000, 10000, 5000, 2000],
            index=0,
            key="pc_classe",
        )

    with col3:
        posicao = st.selectbox(
            "Posição final",
            options=list(BASE_POINTS_50K_QUADRO_A.keys()),
            index=0,
            key="pc_posicao",
        )

    # ----------------------------
    # Tracking: 1 evento por sessão quando o user mexe
    # ----------------------------
    curr = f"{nivel}|{classe}|{posicao}"
    prev = st.session_state.get("_pc_prev_signature")

    # Primeira renderização não conta como uso
    if prev is None:
        st.session_state["_pc_prev_signature"] = curr
    else:
        if curr != prev and not st.session_state.get("_pc_ga_sent"):
            st.session_state["_pc_ga_sent"] = True
            _ga_points_used_event(nivel=nivel, classe=classe, posicao=posicao)

        st.session_state["_pc_prev_signature"] = curr

    # ----------------------------
    # Cálculo e UI
    # ----------------------------
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

    # ✅ Nota única, com parágrafos entre linhas (mantida)
    st.markdown("""
<div style="line-height:1.8">

<span style="color:#0A84FF; font-weight:600;">- M1</span> os primeiros 100 no ranking<br><br>
<span style="color:#0A84FF; font-weight:600;">- M2</span> do 101 ao 250<br><br>
<span style="color:#0A84FF; font-weight:600;">- M3</span> do 251 ao 500<br><br>
<span style="color:#0A84FF; font-weight:600;">- M4</span> do 501 ao 750<br><br>
<span style="color:#0A84FF; font-weight:600;">- M5</span> do 751 ao 1000<br><br>
<span style="color:#0A84FF; font-weight:600;">- M6</span> do 1001 até ao último looser<br><br>

<span style="color:#FF2D55; font-weight:600;">- F1</span> as primeiras 100 no ranking<br><br>
<span style="color:#FF2D55; font-weight:600;">- F2</span> da 101 ao 150<br><br>
<span style="color:#FF2D55; font-weight:600;">- F3</span> da 151 ao 300<br><br>
<span style="color:#FF2D55; font-weight:600;">- F4</span> da 301 ao 450<br><br>
<span style="color:#FF2D55; font-weight:600;">- F5</span> da 451 ao 600<br><br>
<span style="color:#FF2D55; font-weight:600;">- F6</span> da 601 até à última looser

</div>
""", unsafe_allow_html=True)


# Se quiseres testar este ficheiro isoladamente:
if __name__ == "__main__":
    st.set_page_config(page_title="Calculadora de Pontos", layout="centered")
    render_points_calculator()
