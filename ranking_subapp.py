import streamlit as st
from tiesports_scraper import fetch_player_points_playwright

def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nome ou nº de licença (clica automaticamente em 'Ver mais').")

    gender = st.selectbox("Bloco", ["Masculinos", "Femininos", "Mistos"], index=0)
    query = st.text_input("Nome ou nº licença", placeholder="Ex: Lucas Francisco ou 17017")

    if st.button("🔎 Procurar", use_container_width=True, disabled=not query.strip()):
        with st.spinner("A consultar ranking…"):
            res = fetch_player_points_playwright(query.strip(), gender_block=gender)

        if not res.get("found"):
            st.warning(res.get("error", "Não encontrei esse atleta."))
            return

        st.success("Encontrado ✅")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ranking", str(res.get("ranking", "—")))
        c2.metric("Pontos", res.get("pontos", "—"))
        c3.metric("Licença", res.get("licenca", "—"))
        c4.metric("Data", res.get("date", "—"))

        st.write({"Jogador": res.get("jogador", "—")})
