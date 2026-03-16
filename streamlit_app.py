import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import streamlit as st

ROOT = Path(__file__).resolve().parent
APP_URL = "http://127.0.0.1:8787"
STATE_URL = f"{APP_URL}/api/state"
REQUIRED_SECRETS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SHEETS_WEBHOOK_URL",
]


def apply_streamlit_secrets():
    for key in REQUIRED_SECRETS + ["APP_TIMEZONE"]:
        if key in st.secrets and not os.environ.get(key):
            os.environ[key] = str(st.secrets[key])


def node_command():
    if shutil.which("node"):
        return ["node", "src/server.js"]
    if shutil.which("nodejs"):
        return ["nodejs", "src/server.js"]
    return None


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def app_ready() -> bool:
    try:
        with urlopen(STATE_URL, timeout=1.5) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def ensure_server():
    if app_ready():
        return True, "running"

    command = node_command()
    if not command:
        return False, "missing_node"

    process = st.session_state.get("dry_server_process")
    if process and process.poll() is None:
        for _ in range(12):
            if app_ready():
                return True, "running"
            time.sleep(0.5)
        return False, "starting"

    env = os.environ.copy()
    env.setdefault("PORT", "8787")
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    st.session_state["dry_server_process"] = process

    for _ in range(20):
        if app_ready():
            return True, "started"
        time.sleep(0.5)

    return False, "starting"


def secret_status():
    rows = []
    for key in REQUIRED_SECRETS:
        rows.append(
            {
                "Key": key,
                "Status": "OK" if os.environ.get(key) else "Missing",
            }
        )
    return rows


st.set_page_config(
    page_title="Status Dry Launcher",
    page_icon="🧾",
    layout="centered",
)

apply_streamlit_secrets()

st.title("Status Dry Launcher")
st.caption("Launcher Streamlit untuk membuka laporan dry berbasis Node.")

with st.container(border=True):
    st.markdown(
        "Aplikasi utama tetap berjalan dari `src/server.js`. "
        "Halaman ini hanya menyiapkan environment Streamlit dan memeriksa apakah server dry sudah siap."
    )

ok, state = ensure_server()

if ok:
    st.success("Server laporan dry siap.")
    st.link_button("Buka aplikasi dry", APP_URL, use_container_width=True)
else:
    if state == "missing_node":
        st.error("Node.js tidak ditemukan di environment ini. Pastikan package `nodejs` tersedia.")
    else:
        st.warning("Server dry belum siap. Tunggu sebentar lalu refresh halaman ini.")

with st.expander("Status environment", expanded=True):
    st.dataframe(secret_status(), use_container_width=True, hide_index=True)
    st.code(
        "\n".join(
            [
                "Main file: streamlit_app.py",
                "Node entry: src/server.js",
                "App URL: http://127.0.0.1:8787",
                f"Server ready: {'yes' if ok else 'no'}",
            ]
        ),
        language="text",
    )

with st.expander("Catatan deployment", expanded=False):
    st.markdown(
        "- Streamlit ini berfungsi sebagai launcher/diagnostic untuk app Node.\n"
        "- Secrets yang perlu diisi di Streamlit: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SHEETS_WEBHOOK_URL`.\n"
        "- Jika deploy target tidak mengizinkan akses ke server Node internal, perlu host web terpisah atau proxy tambahan."
    )
