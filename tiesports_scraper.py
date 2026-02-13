# tiesports_scraper.py
import re
from typing import Dict, Any, Optional

from unidecode import unidecode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError

SUMMARY_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode(s or "").strip().lower())


def _extract_date_from_header(text: str) -> str:
    # Ex: "Masculinos [10 Feb 2026]"
    m = re.search(r"\[(.*?)\]", text or "")
    return (m.group(1).strip() if m else "")


def fetch_player_points_playwright(
    query: str,
    *,
    gender_block: str = "Masculinos",   # "Masculinos" / "Femininos" / "Mistos"
    timeout_ms: int = 60_000,
) -> Dict[str, Any]:
    """
    Abre a página "resumo" (top 10), clica "Ver mais" do bloco escolhido,
    e na página completa (com filtros) pesquisa por Nome/Licença.
    Devolve ranking + pontos + licença + nome (quando encontra).
    """
    q = (query or "").strip()
    if not q:
        return {"found": False, "error": "Pesquisa vazia."}

    qn = _norm(q)

    try:
        with sync_playwright() as p:
            # Args importantes para correr em containers (Streamlit Cloud)
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage"]

            try:
                browser = p.chromium.launch(headless=True, args=launch_args)
            except PWError as e:
                # erro típico quando falta instalar o chromium
                return {
                    "found": False,
                    "error": (
                        "Não consegui iniciar o Chromium do Playwright. "
                        "Isto acontece quando os browsers não foram instalados no ambiente.\n\n"
                        "Confirma no Streamlit Cloud que o Chromium foi instalado (ex: via postBuild ou dependência que o instale).\n"
                        f"Detalhe: {e}"
                    ),
                }

            page = browser.new_page()

            try:
                page.goto(SUMMARY_URL, wait_until="domcontentloaded", timeout=timeout_ms)

                # 1) Header do bloco (ex: "Masculinos [10 Feb 2026]")
                hdr = page.locator(f"text=/{gender_block}\\s*\\[.*\\]/").first
                hdr.wait_for(state="visible", timeout=30_000)

                hdr_text = (hdr.text_content() or "").strip()
                ranking_date = _extract_date_from_header(hdr_text)

                # 2) Clicar no "Ver mais" imediatamente a seguir ao header
                # Preferimos clicar em <a> / <button> com texto "Ver mais"
                ver_mais = hdr.locator(
                    "xpath=following::a[normalize-space()='Ver mais'][1] | "
                    "following::button[normalize-space()='Ver mais'][1]"
                ).first

                # fallback: se não encontrar como <a>/<button>, tenta por texto global
                try:
                    ver_mais.click(timeout=20_000)
                except Exception:
                    page.locator("text=Ver mais").first.click(timeout=20_000)

                # A página completa pode carregar via navegação
                page.wait_for_load_state("domcontentloaded")

                # 3) Esperar pelo input "Nome/Licença"
                # O teu screenshot tem label "Nome/Licença"
                name_input = page.locator(
                    "xpath=//label[contains(., 'Nome') or contains(., 'Licença') or contains(., 'Licenca')]/following::input[1]"
                ).first
                name_input.wait_for(state="visible", timeout=30_000)
                name_input.fill(q)

                # 4) Clicar FILTRAR
                page.locator("text=FILTRAR").first.click(timeout=20_000)

                # 5) Esperar tabela e procurar linha
                rows = page.locator("table tbody tr")
                rows.first.wait_for(timeout=30_000)

                # Nota: na página completa as colunas (segundo o teu screenshot) são:
                # 0 ranking, 1 variação, 2 licença, 3 jogador, 4 pontos, ...
                for i in range(min(rows.count(), 50)):
                    tds = rows.nth(i).locator("td")
                    if tds.count() < 5:
                        continue

                    ranking_txt = (tds.nth(0).inner_text() or "").strip()
                    licenca_txt = (tds.nth(2).inner_text() or "").strip()
                    jogador_txt = (tds.nth(3).inner_text() or "").strip()
                    pontos_txt = (tds.nth(4).inner_text() or "").strip()

                    if qn in _norm(jogador_txt) or qn == _norm(licenca_txt):
                        ranking_int: Optional[int] = None
                        try:
                            ranking_int = int(re.sub(r"\D+", "", ranking_txt)) if ranking_txt else None
                        except Exception:
                            ranking_int = None

                        return {
                            "found": True,
                            "date": ranking_date,
                            "ranking": ranking_int,
                            "licenca": licenca_txt,
                            "jogador": jogador_txt,
                            "pontos": pontos_txt,
                        }

                return {
                    "found": False,
                    "date": ranking_date,
                    "error": "Não encontrei esse atleta nos resultados (tenta nome mais completo ou nº de licença).",
                }

            except PWTimeout:
                return {"found": False, "error": "Timeout ao carregar página/elementos (o site pode estar lento)."}
            except Exception as e:
                return {"found": False, "error": f"Erro inesperado: {e}"}
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        # falha em iniciar o Playwright
        return {"found": False, "error": f"Falha a iniciar Playwright: {e}"}
