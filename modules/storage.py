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
    if ws.row_values(1) != headers:
        ws.clear()
        ws.append_row(headers)

    ws.append_row([
        row.get("torneio_id",""),
        row.get("torneio_nome",""),
        row.get("timestamp",""),
        row.get("nome",""),
        row.get("telefone",""),
        row.get("foto_url",""),
        row.get("storage","dropbox"),
    ])


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

def upload_photo_to_dropbox(file_bytes: bytes, torneio_id: str, filename: str):
    import dropbox
    from dropbox.files import WriteMode
    from dropbox.sharing import SharedLinkSettings
    from dropbox.exceptions import ApiError, AuthError

    token = st.secrets.get("DROPBOX_TOKEN", "").strip()
    if not token:
        return None

    try:
        dbx = dropbox.Dropbox(token)

        base = DROPBOX_BASE_PATH.rstrip("/")
        folder_path = f"{base}/{torneio_id}"
        dropbox_path = f"{folder_path}/{filename}"

        try:
            dbx.files_create_folder_v2(base)
        except:
            pass

        try:
            dbx.files_create_folder_v2(folder_path)
        except:
            pass

        dbx.files_upload(file_bytes, dropbox_path, mode=WriteMode.overwrite, mute=True)

        try:
            link_meta = dbx.sharing_create_shared_link_with_settings(
                dropbox_path,
                settings=SharedLinkSettings()
            )
            url = link_meta.url
        except ApiError:
            links = dbx.sharing_list_shared_links(path=dropbox_path).links
            url = links[0].url if links else None

        return url.replace("?dl=0", "?raw=1") if url else None

    except AuthError:
        return None


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


def save_inscricao(torneio: dict, nome: str, telefone: str, foto):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    telefone_norm = normalize_phone(telefone)

    file_bytes = foto.getvalue()
    ext = (foto.name.split(".")[-1] if foto and foto.name and "." in foto.name else "jpg").lower()
    filename = f"{torneio['id']}_{int(dt.datetime.now().timestamp())}_{safe_slug(nome)}.{ext}"

    foto_url = upload_photo_to_dropbox(file_bytes, torneio["id"], filename) or ""

    row = {
        "torneio_id": torneio["id"],
        "torneio_nome": torneio["nome"],
        "timestamp": ts,
        "nome": nome.strip(),
        "telefone": telefone_norm,
        "foto_url": foto_url,
        "storage": "dropbox",
    }

    append_to_sheet(row)
