# tiesports_scraper.py
import os
import re
import sys
import subprocess
from typing import Dict, Any, Optional

from unidecode import unidecode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError


SUMMARY_URL = "https://tour.tiesports.com/fpp/weekly_rankings?rank=absolutos"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unidecode(s or "").strip().lower())


def _chromium_installed() -> bool:
    """
    Heurística simples: Playwright guarda browsers em ~/.cache/ms-playwright.
    Se existir algo de chromium lá dentro, assumimos instalado.
    """
    cache_dir = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.isdir(cache_dir):
        return False
    try:
        for name in os.listdir(cache_dir):
            if "chromium" in name.lower():
                return True
    except Exception:
        return False
    return False


def _ensure_chromium() -> None:
    """
    Garante que o Chromium do Playwright está instalado.
    - No Streamlit Cloud, o postBuild às vezes não corre.
    - Isto resolve: instala em runtime se faltar.
    """
    if _chromium_installed():
        return

    # Tenta instalar. (No primeiro run pode demorar um bocado.)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        # Se falhar por permissões, deixamos o erro aparecer no launch.
        pass


def fetch_player_points_playwright(
    query: str,
    *,
    gender_block: str = "Masculinos",   # "Masculinos" / "Femininos" / "Mistos"
    timeout_ms: int = 60_000,
) -> Dict[str, Any]:
    """
    1) Abre a página resumo (top 10)
    2) Clica "Ver mais" (bloco escolhido)
    3) Na página completa, pesquisa por Nome/Licença, clica FILTRAR
    4) Extrai ranking + pontos + licença + jogador
    """
    q = (query or "").strip()
    if not q:
        return {"found": False, "error": "Pesquisa vazia."}

    _ensure_chromium()

    qn = _norm(q)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                # importantíssimo em containers
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except PWError as e:
            return {
                "found": False,
                "error": (
                    "Não consegui iniciar o Chromium do Playwright. "
                    "Isto normalmente acontece quando o Chromium não foi instalado.\n\n"
                    "Confirma que tens um ficheiro `postBuild` com `python -m playwright install chromium` "
                    "OU deixa o fallback tentar instalar (pode falhar por permissões).\n\n"
                    f"Detalhe: {e}"
                ),
            }

        page = browser.new_page()

        try:
            page.goto(SUMMARY_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            # 1) Header do bloco (ex: "Masculinos [10 Feb 2026]")
            hdr = page.locator(f"text=/{gender_block}\\s*\\[.*\\]/").first
            hdr.wait_for(state="visible", timeout=30_000)

            # 2) Clicar no "Ver mais" a seguir ao header
            ver_mais = hdr.locator(
                "xpath=following::a[normalize-space()='Ver mais'][1] | "
                "following::button[normalize-space()='Ver mais'][1]"
            ).first

            try:
                ver_mais.click(timeout=20_000)
            except Exception:
                # fallback: click no primeiro "Ver mais" da página
                page.locator("text=Ver mais").first.click(timeout=20_000)

            page.wait_for_load_state("domcontentloaded")

            # 3) Esperar pelo input "Nome/Licença" e preencher
            name_input = page.locator(
                "xpath=//label[contains(., 'Nome') or contains(., 'Licença') or contains(., 'Licenca')]/following::input[1]"
            ).first
            name_input.wait_for(state="visible", timeout=30_000)
            name_input.fill(q)

            # 4) Clicar FILTRAR
            page.locator("text=FILTRAR").first.click(timeout=20_000)

            # 5) Esperar pela tabela e procurar a linha
            rows = page.locator("table tbody tr")
            rows.first.wait_for(timeout=30_000)

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
                        "ranking": ranking_int,
                        "licenca": licenca_txt,
                        "jogador": jogador_txt,
                        "pontos": pontos_txt,
                    }

            return {"found": False, "error": "Não encontrei esse atleta (tenta nome completo ou nº de licença)."}

        except PWTimeout:
            return {"found": False, "error": "Timeout (site lento ou bloqueado)."}
        except Exception as e:
            return {"found": False, "error": f"Erro inesperado: {e}"}
        finally:
            try:
                browser.close()
            except Exception:
                pass
