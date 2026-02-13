# tiesports_scraper.py
import re
from typing import Optional, Dict, Any
from unidecode import unidecode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SUMMARY_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode(s or "").strip().lower())

def fetch_player_points_playwright(
    query: str,
    *,
    gender_block: str = "Masculinos",   # "Masculinos" / "Femininos" / "Mistos"
    timeout_ms: int = 60_000,
) -> Dict[str, Any]:
    """
    Abre a página resumo, clica "Ver mais" do bloco escolhido (por defeito Masculinos),
    e na página completa pesquisa por Nome/Licença.
    Devolve ranking + pontos + licença + nome (quando encontra).
    """
    q = (query or "").strip()
    if not q:
        return {"found": False, "error": "Pesquisa vazia."}

    qn = _norm(q)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(SUMMARY_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            # 1) Encontrar o cabeçalho do bloco (ex: "Masculinos [10 Feb 2026]")
            hdr = page.locator(f"text=/{gender_block}\\s*\\[.*\\]/").first
            hdr.wait_for(state="visible", timeout=30_000)

            # 2) Clicar no "Ver mais" imediatamente a seguir a esse bloco
            # (usa xpath following para apanhar o primeiro "Ver mais" a seguir ao header)
            ver_mais = hdr.locator(
                "xpath=following::a[normalize-space()='Ver mais'][1] | "
                "following::button[normalize-space()='Ver mais'][1] | "
                "following::*[normalize-space()='Ver mais'][1]"
            ).first

            ver_mais.click(timeout=20_000)
            page.wait_for_load_state("domcontentloaded")

            # 3) Agora estamos na página completa (com filtros e tabela).
            # Esperar pelo input "Nome/Licença" e preencher
            name_input = page.locator(
                "xpath=//label[contains(., 'Nome') or contains(., 'Licença')]/following::input[1]"
            ).first
            name_input.wait_for(state="visible", timeout=30_000)
            name_input.fill(q)

            # 4) Clicar FILTRAR
            page.locator("text=FILTRAR").first.click(timeout=20_000)

            # 5) Esperar pela tabela e procurar a linha
            rows = page.locator("table tbody tr")
            rows.first.wait_for(timeout=30_000)

            # cada linha (segundo o teu screenshot): ranking, variação, licença, jogador, pontos, ...
            for i in range(min(rows.count(), 50)):
                tds = rows.nth(i).locator("td")
                if tds.count() < 5:
                    continue

                ranking_txt = (tds.nth(0).inner_text() or "").strip()
                licenca_txt = (tds.nth(2).inner_text() or "").strip()
                jogador_txt = (tds.nth(3).inner_text() or "").strip()
                pontos_txt  = (tds.nth(4).inner_text() or "").strip()

                if qn in _norm(jogador_txt) or qn == _norm(licenca_txt):
                    # ranking int (se possível)
                    ranking_int = None
                    try:
                        ranking_int = int(re.sub(r"\D+", "", ranking_txt)) if ranking_txt else None
                    except Exception:
                        ranking_int = None

                    browser.close()
                    return {
                        "found": True,
                        "ranking": ranking_int,
                        "licenca": licenca_txt,
                        "jogador": jogador_txt,
                        "pontos": pontos_txt,
                    }

            browser.close()
            return {"found": False, "error": "Não encontrei esse atleta nos resultados (tenta nome mais completo ou licença)."}

        except PWTimeout:
            browser.close()
            return {"found": False, "error": "Timeout ao carregar página/elementos (o site pode estar lento)."}
        except Exception as e:
            browser.close()
            return {"found": False, "error": f"Erro: {e}"}
