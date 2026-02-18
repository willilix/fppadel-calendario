import re
import datetime as dt
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

DROPBOX_BASE_PATH = "/Torneios/Fotos"


# =================================================
# GOOGLE SHEETS
# =================================================

@st.cache_resource
def google_spreadsheet():
    sa_info = dict(st.secrets["GCP_SERVICE_ACCOUNT"])

    pk = sa_info.get("private_key", "")
    if "\\n" in pk:
        sa_info["private_key"] = pk.replace("\\n", "\n")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)

    gc = gspread.authorize(creds)
    return gc.open_by_key(st.secrets["SHEET_ID"])


def google_ws(name: str):
    return google_spreadsheet().worksheet(name)


def read_sheet() -> pd.DataFrame:
    ws = google_ws("inscricoes")
    values = ws.get_all_values()
    if len(values) <= 1:
        cols = values[0] if values else [
            "torneio_id","torneio_nome","timestamp",
            "nome","telefone","foto_url","storage"
        ]
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(values[1:], columns=values[0])


def append_to_sheet(row: dict):
    ws = google_ws("inscricoes")
    headers = [
        "torneio_id","torneio_nome","timestamp",
        "nome","telefone","foto_url","storage"
    ]
    # ⚠️ Não limpar a sheet automaticamente se os headers diferirem.
    # Isso podia apagar dados existentes. Em vez disso, tenta alinhar e prossegue.
    existing = ws.row_values(1)
    if existing != headers:
        if not existing:
            ws.append_row(headers)
        else:
            # Se já existem headers diferentes, não apagamos. Apenas registamos.
            st.warning("Atenção: os headers da sheet 'inscricoes' não estão na ordem esperada. Vou continuar a gravar por ordem fixa.")

    ws.append_row([
        row.get("torneio_id",""),
        row.get("torneio_nome",""),
        row.get("timestamp",""),
        row.get("nome",""),
        row.get("telefone",""),
        row.get("foto_url",""),
        row.get("storage",""),
    ], value_input_option="USER_ENTERED")


def read_torneios():
    ws = google_ws("Torneios")
    values = ws.get_all_values()
    if len(values) <= 1:
        return []

    headers = values[0]
    rows = values[1:]

    torneios = []
    for row in rows:
        data = dict(zip(headers, row))

        if str(data.get("ativo","")).upper() != "TRUE":
            continue

        try:
            vagas = int(data.get("vagas") or 0)
        except:
            vagas = 0

        torneios.append({
            "id": data.get("id"),
            "nome": data.get("nome"),
            "data": data.get("data"),
            "local": data.get("local"),
            "descricao": data.get("descricao",""),
            "img": data.get("imagem_url"),
            "vagas": vagas,
        })

    return torneios


# =================================================
# DROPBOX
# =================================================

def _get_dropbox_client():
    """Cria um cliente Dropbox usando refresh token (não expira na prática)."""
    import dropbox
    from dropbox.exceptions import AuthError

    refresh = (st.secrets.get("DROPBOX_REFRESH_TOKEN", "") or "").strip()
    app_key = (st.secrets.get("DROPBOX_APP_KEY", "") or "").strip()
    app_secret = (st.secrets.get("DROPBOX_APP_SECRET", "") or "").strip()

    if not (refresh and app_key and app_secret):
        st.error("Faltam secrets Dropbox: DROPBOX_REFRESH_TOKEN / DROPBOX_APP_KEY / DROPBOX_APP_SECRET")
        return None

    try:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=refresh,
            app_key=app_key,
            app_secret=app_secret,
        )
        # valida cedo (se houver problema de scopes/revogação dá logo erro)
        dbx.users_get_current_account()
        return dbx
    except AuthError as e:
        st.error("Dropbox: refresh token inválido/revogado ou sem permissões.")
        st.exception(e)
        return None
    except Exception as e:
        st.error("Dropbox: erro ao criar cliente com refresh token.")
        st.exception(e)
        return None


def _ensure_dropbox_folder(dbx, path: str):
    """Cria pastas Dropbox de forma incremental (evita erro quando o pai não existe)."""
    import dropbox
    from dropbox.exceptions import ApiError

    # Normalizar
    path = (path or "").strip()
    if not path or path == "/":
        return

    # Criar cada segmento: /Torneios, /Torneios/Fotos, /Torneios/Fotos/<id>
    parts = [p for p in path.split("/") if p]
    curr = ""
    for p in parts:
        curr += f"/{p}"
        try:
            dbx.files_create_folder_v2(curr)
        except ApiError:
            # já existe ou sem permissões; deixamos subir para o caller em casos críticos
            pass


def upload_photo_to_dropbox(file_bytes: bytes, torneio_id: str, filename: str):
    """Faz upload para Dropbox e devolve (public_url, dropbox_path)."""
    from dropbox.files import WriteMode
    from dropbox.sharing import SharedLinkSettings
    from dropbox.exceptions import ApiError

    dbx = _get_dropbox_client()
    if dbx is None:
        return "", ""

    try:
        base = DROPBOX_BASE_PATH.rstrip("/")
        folder_path = f"{base}/{torneio_id}"
        dropbox_path = f"{folder_path}/{filename}"

        # garantir estrutura
        _ensure_dropbox_folder(dbx, base)
        _ensure_dropbox_folder(dbx, folder_path)

        # upload
        dbx.files_upload(file_bytes, dropbox_path, mode=WriteMode.overwrite, mute=True)

        # link público (ou reutilizar existente)
        url = ""
        try:
            link_meta = dbx.sharing_create_shared_link_with_settings(
                dropbox_path,
                settings=SharedLinkSettings()
            )
            url = link_meta.url
        except ApiError:
            links = dbx.sharing_list_shared_links(path=dropbox_path).links
            url = links[0].url if links else ""

        public_url = url.replace("?dl=0", "?raw=1") if url else ""
        return public_url, dropbox_path

    except Exception as e:
        st.error("Erro inesperado no upload para Dropbox.")
        st.exception(e)
        return "", ""


# =================================================
# HELPERS
# =================================================

def normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    phone = re.sub(r"[^\d+]", "", phone)
    return phone


def safe_slug(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
    return text[:60] if text else "user"


def _extract_upload(foto):
    """
    Aceita:
      - streamlit.runtime.uploaded_file_manager.UploadedFile (st.file_uploader)
      - dict guardado em session_state: {"bytes":..., "name":..., "type":...}
    Devolve: (bytes, original_name, content_type)
    """
    if foto is None:
        return b"", "", ""

    # dict (session_state stash)
    if isinstance(foto, dict):
        b = foto.get("bytes") or b""
        n = foto.get("name") or "foto.jpg"
        t = foto.get("type") or ""
        return b, n, t

    # UploadedFile
    try:
        b = foto.getvalue()
        n = getattr(foto, "name", "") or "foto.jpg"
        t = getattr(foto, "type", "") or ""
        return b, n, t
    except Exception:
        return b"", "", ""


def save_inscricao(torneio: dict, nome: str, telefone: str, foto):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    telefone_norm = normalize_phone(telefone)

    file_bytes, original_name, _content_type = _extract_upload(foto)

    foto_url = ""
    storage_path = ""

    if file_bytes:
        ext = "jpg"
        if original_name and "." in original_name:
            ext = original_name.split(".")[-1].lower()
        filename = f"{torneio['id']}_{int(dt.datetime.now().timestamp())}_{safe_slug(nome)}.{ext}"

        try:
            foto_url, storage_path = upload_photo_to_dropbox(file_bytes, torneio["id"], filename)
        except Exception as e:
            st.error("Upload para Dropbox falhou — vou gravar a inscrição sem foto.")
            st.exception(e)
            foto_url, storage_path = "", ""

    row = {
        "torneio_id": torneio.get("id",""),
        "torneio_nome": torneio.get("nome",""),
        "timestamp": ts,
        "nome": (nome or "").strip(),
        "telefone": telefone_norm,
        "foto_url": foto_url,
        # aqui guardamos o caminho real (ou vazio)
        "storage": storage_path or "dropbox",
    }

    append_to_sheet(row)
