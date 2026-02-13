import streamlit as st
from tiesports_scraper import search_weekly_ranking

def render_ranking():
    st.markdown("## 🏆 Ranking semanal (TieSports/FPP)")
    st.caption("Pesquisa por nome ou nº de licença (entra automaticamente via 'Ver mais').")

    gender = st.selectbox("Bloco", ["Masculinos", "Femininos", "Mistos"], index=0)
    query = st.text_input("Nome ou nº licença", placeholder="Ex: 17017")

    if st.button("🔎 Procurar", use_container_width=True, disabled=not query.strip()):
        with st.spinner("A consultar ranking…"):
            res = search_weekly_ranking(query.strip(), gender_block=gender)

        if not res.get("found"):
            st.warning(res.get("error", "Não encontrei."))
            return

        d = res["data"]
        st.success("Encontrado ✅")

        c1, c2, c3 = st.columns(3)
        c1.metric("Ranking", d.get("ranking", "—"))
        c2.metric("Pontos", d.get("pontos", "—"))
        c3.metric("Licença", d.get("licenca", "—"))

        st.write({
            "Jogador": d.get("jogador", ""),
            "Clube": d.get("clube", ""),
            "Nível": d.get("nivel", ""),
            "Escalão": d.get("escalao", ""),
            "Torneios": d.get("torneios", ""),
        })
