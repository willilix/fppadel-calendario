import streamlit as st

def render_rankings():
    st.subheader("Rankings (TieSports)")
    st.caption("Abre o ranking no site oficial.")
    st.link_button(
        "🏆 Abrir Rankings",
        "https://tour.tiesports.com/fpp/weekly_rankings",
        use_container_width=True,
    )
