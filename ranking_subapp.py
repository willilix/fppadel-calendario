import streamlit as st
from tiesports_scraper import fetch_player_points_playwright


def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nome ou nº de licença (clica automaticamente em 'Ver mais').")

    gender = st.selectbox("Bloco", ["Masculinos", "Femininos", "Mistos"], index=0)
    query = st.text_input("Nome ou nº licença", placeholder="Ex: 17017")

    if st.button("🔎 Procurar", use_container_width=True, disabled=not query.strip()):
        with st.spinner("A consultar ranking… (na 1ª vez pode demorar se tiver de instalar o Chromium)"):
            res = fetch_player_points_playwright(query.strip(), gender_block=gender)

        if not res.get("found"):
            st.warning(res.get("error", "Não encontrei esse atleta."))
            return

        st.success("Encontrado ✅")
        c1, c2, c3 = st.columns(3)
        c1.metric("Ranking", str(res.get("ranking", "—")))
        c2.metric("Pontos", res.get("pontos", "—"))
        c3.metric("Licença", res.get("licenca", "—"))
        st.write({"Jogador": res.get("jogador", "—")})
