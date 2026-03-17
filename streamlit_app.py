import html
import json
import os
import shutil
import subprocess
import time
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
LOCAL_APP_URL = "http://127.0.0.1:8787"
LOCAL_STATE_URL = f"{LOCAL_APP_URL}/api/state"
LOCAL_SAMPLE_URL = f"{LOCAL_APP_URL}/api/sample"
DRAFT_FILE = ROOT / "storage" / "streamlit-operator-draft.json"
REQUIRED_SECRETS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SHEETS_WEBHOOK_URL"]
STATUS_OPTIONS = [
    "KOSONG",
    "TIDAK_DIPAKAI",
    "PROSES",
    "SIAP_TURUN",
    "SELESAI_DRY",
    "TURUN_PACKING",
    "DRY_ULANG",
]
STATUS_LABELS = {
    "KOSONG": "Kosong",
    "TIDAK_DIPAKAI": "Tidak dipakai / rusak",
    "PROSES": "Lagi Isi",
    "SIAP_TURUN": "Menunggu Turun",
    "SELESAI_DRY": "Menunggu Turun",
    "TURUN_PACKING": "Lagi Keluarkan",
    "DRY_ULANG": "Sedang Dry",
}


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


def app_ready() -> bool:
    try:
        with urlopen(LOCAL_STATE_URL, timeout=1.5) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def ensure_server():
    if app_ready():
        return True, "running"

    command = node_command()
    if not command:
        return False, "missing_node"

    process = st.session_state.get("_dry_server_process")
    if process and process.poll() is None:
        for _ in range(10):
            if app_ready():
                return True, "running"
            time.sleep(0.5)
        return False, "starting"

    env = os.environ.copy()
    env.setdefault("HOST", "127.0.0.1")
    env.setdefault("PORT", "8787")
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    st.session_state["_dry_server_process"] = process

    for _ in range(20):
        if app_ready():
            return True, "started"
        time.sleep(0.5)

    return False, "starting"


def api_json(url, method="GET", payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as err:
        raw = err.read().decode("utf-8") if err.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        message = parsed.get("error") or raw or str(err)
        raise RuntimeError(message) from err
    except URLError as err:
        raise RuntimeError(str(err.reason)) from err


def read_json(file_path: Path, fallback):
    try:
        return json.loads(file_path.read_text("utf-8"))
    except Exception:
        return fallback


def write_json(file_path: Path, value):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp = file_path.with_suffix(file_path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), "utf-8")
    temp.replace(file_path)


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def non_empty(value):
    text = clean_text(value)
    return text or None


def normalize_clock(value):
    raw = clean_text(value)
    if not raw:
        return ""
    text = raw.replace(".", ":")
    import re

    matched = re.match(r"^(\d{1,2}):(\d{1,2})$", text)
    if matched:
        hh = int(matched.group(1))
        mm = int(matched.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
        return ""

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""
    if len(digits) <= 2:
        hh, mm = int(digits), 0
    elif len(digits) == 3:
        hh, mm = int(digits[0]), int(digits[1:])
    elif len(digits) == 4:
        hh, mm = int(digits[:2]), int(digits[2:])
    else:
        return ""
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return f"{hh:02d}:{mm:02d}"
    return ""


def normalize_defrost(value):
    if value is True or value is False:
        return value
    text = clean_text(value).lower()
    if text in {"yes", "true"}:
        return True
    if text in {"no", "false"}:
        return False
    return None


def split_names(value):
    return [item.strip() for item in clean_text(value).split(",") if item.strip()]


def empty_slot(slot_no: int):
    return {
        "slot_no": slot_no,
        "status_enum": "KOSONG",
        "tgl_masuk": None,
        "jam_masuk": None,
        "tgl_defros": None,
        "jam_defros": None,
        "jam_estimasi_defrost": None,
        "jam_estimasi_keluar": None,
        "petugas_masuk": None,
        "tgl_selesai_dry": None,
        "jam_selesai_dry": None,
        "partial_out": False,
        "jam_keluar_sebagian": None,
        "jam_estimasi_sisa": None,
        "partial_unload_content": None,
        "partial_unload_note": None,
        "petugas_keluar": None,
        "tgl_turun_packing": None,
        "jam_turun_packing": None,
        "needs_defrost": None,
        "status_isi": None,
        "atas_izin": None,
        "notes": None,
    }


def infer_status(slot):
    if clean_text(slot.get("jam_turun_packing")) or clean_text(slot.get("tgl_turun_packing")):
        return "TURUN_PACKING"
    if clean_text(slot.get("jam_selesai_dry")) or clean_text(slot.get("tgl_selesai_dry")):
        return "SELESAI_DRY"
    if clean_text(slot.get("jam_masuk")) or clean_text(slot.get("tgl_masuk")) or clean_text(slot.get("jam_defros")):
        return "PROSES"
    if clean_text(slot.get("jam_estimasi_keluar")) or clean_text(slot.get("status_isi")) or clean_text(slot.get("atas_izin")):
        return "PROSES"
    return ""


def normalize_slot(slot):
    base = empty_slot(int(slot.get("slot_no") or 1))
    base.update(slot or {})
    base["status_enum"] = base.get("status_enum") if base.get("status_enum") in STATUS_OPTIONS else "KOSONG"
    for key in [
        "jam_masuk",
        "jam_defros",
        "jam_estimasi_defrost",
        "jam_estimasi_keluar",
        "jam_selesai_dry",
        "jam_keluar_sebagian",
        "jam_estimasi_sisa",
        "jam_turun_packing",
    ]:
        base[key] = non_empty(normalize_clock(base.get(key)))
    for key in [
        "tgl_masuk",
        "tgl_defros",
        "tgl_selesai_dry",
        "tgl_turun_packing",
        "petugas_masuk",
        "petugas_keluar",
        "status_isi",
        "atas_izin",
        "notes",
        "partial_unload_content",
        "partial_unload_note",
    ]:
        base[key] = non_empty(base.get(key))
    base["needs_defrost"] = normalize_defrost(base.get("needs_defrost"))
    base["partial_out"] = bool(base.get("partial_out"))
    inferred = infer_status(base)
    if base["status_enum"] in {"KOSONG", "TIDAK_DIPAKAI"} and inferred:
        base["status_enum"] = inferred
    return base


def normalize_report(report):
    report = deepcopy(report or {})
    meta = report.setdefault("report_meta", {})
    team_start = meta.setdefault("team_start", {})
    team_start.setdefault("shift", "Shift 1")
    team_start.setdefault("members", [])
    work_date = clean_text(meta.get("prd_date")) or str(date.today())
    meta["prd_date"] = work_date
    meta.setdefault("timezone", "Asia/Jakarta")
    report["selected_slot"] = int(report.get("selected_slot") or 1)
    slots = report.get("slots") or []
    by_no = {int(slot.get("slot_no")): normalize_slot(slot) for slot in slots if slot.get("slot_no")}
    report["slots"] = [by_no.get(idx, empty_slot(idx)) for idx in range(1, 12)]
    return report


def load_sample_report():
    try:
        sample = api_json(LOCAL_SAMPLE_URL)
        return normalize_report(sample.get("sample", {}))
    except Exception:
        file_sample = read_json(ROOT / "report.sample.json", {})
        return normalize_report(file_sample)


def load_draft():
    draft = read_json(DRAFT_FILE, {})
    if not draft:
        return None
    return normalize_report(draft)


def save_draft():
    write_json(DRAFT_FILE, st.session_state["report"])


def ensure_app_state():
    if "report" not in st.session_state:
        draft = load_draft()
        st.session_state["report"] = draft or load_sample_report()
        st.session_state["feedback_text"] = ""
        st.session_state["feedback_ok"] = True
        st.session_state["lock"] = None
        st.session_state["team_id"] = "dry-team-1"
        st.session_state["_pending_editor_sync"] = True
        st.session_state["_editor_slot_no"] = None
        sync_header_widgets_from_report(force=True)


def sync_header_widgets_from_report(force=False):
    report = st.session_state["report"]
    meta = report["report_meta"]
    team_start = meta["team_start"]
    members = ", ".join(team_start.get("members") or [])
    defaults = {
        "work_date": datetime.strptime(meta["prd_date"], "%Y-%m-%d").date(),
        "shift": team_start.get("shift") or "Shift 1",
        "members": members,
        "team_finish": clean_text(meta.get("team_finish")),
        "handover_time": clean_text(meta.get("handover_time")),
        "team_id": st.session_state.get("team_id", "dry-team-1"),
        "lock_owner": st.session_state.get("lock_owner")
        or (split_names(members)[0] if split_names(members) else "operator"),
    }
    for key, value in defaults.items():
        if force or key not in st.session_state:
            st.session_state[key] = value


def sync_editor_widgets_from_selected_slot(force=False):
    report = st.session_state["report"]
    slot_no = report["selected_slot"]
    if (
        not force
        and not st.session_state.get("_pending_editor_sync")
        and st.session_state.get("_editor_slot_no") == slot_no
    ):
        return

    slot = report["slots"][slot_no - 1]
    st.session_state["status_enum"] = slot["status_enum"]
    st.session_state["status_isi"] = clean_text(slot.get("status_isi"))
    st.session_state["needs_defrost"] = "yes" if slot.get("needs_defrost") is True else "no"
    st.session_state["jam_masuk"] = clean_text(slot.get("jam_masuk"))
    st.session_state["jam_defros"] = clean_text(slot.get("jam_defros"))
    st.session_state["jam_estimasi_defrost"] = clean_text(slot.get("jam_estimasi_defrost"))
    st.session_state["jam_estimasi_keluar"] = clean_text(slot.get("jam_estimasi_keluar"))
    st.session_state["jam_selesai_dry"] = clean_text(slot.get("jam_selesai_dry"))
    st.session_state["partial_out"] = "yes" if slot.get("partial_out") else "no"
    st.session_state["jam_keluar_sebagian"] = clean_text(slot.get("jam_keluar_sebagian"))
    st.session_state["jam_estimasi_sisa"] = clean_text(slot.get("jam_estimasi_sisa"))
    st.session_state["partial_unload_content"] = clean_text(slot.get("partial_unload_content"))
    st.session_state["partial_unload_note"] = clean_text(slot.get("partial_unload_note"))
    st.session_state["jam_turun_packing"] = clean_text(slot.get("jam_turun_packing"))
    st.session_state["petugas_masuk"] = clean_text(slot.get("petugas_masuk"))
    st.session_state["petugas_keluar"] = clean_text(slot.get("petugas_keluar"))
    st.session_state["atas_izin"] = clean_text(slot.get("atas_izin"))
    st.session_state["notes"] = clean_text(slot.get("notes"))
    st.session_state["_editor_slot_no"] = slot_no
    st.session_state["_pending_editor_sync"] = False


def sync_report_from_widgets():
    report = st.session_state["report"]
    meta = report["report_meta"]
    team_start = meta["team_start"]
    work_date = st.session_state["work_date"].isoformat() if isinstance(st.session_state["work_date"], date) else str(st.session_state["work_date"])
    meta["prd_date"] = work_date
    team_start["shift"] = st.session_state["shift"]
    team_start["members"] = split_names(st.session_state["members"])
    team_start["label"] = " & ".join(team_start["members"]) if team_start["members"] else ""
    meta["team_finish"] = non_empty(st.session_state["team_finish"])
    meta["handover_time"] = non_empty(normalize_clock(st.session_state["handover_time"]))

    slot = report["slots"][report["selected_slot"] - 1]
    slot["status_enum"] = st.session_state["status_enum"]
    slot["status_isi"] = non_empty(st.session_state["status_isi"])
    slot["needs_defrost"] = st.session_state["needs_defrost"] == "yes"
    slot["jam_masuk"] = non_empty(normalize_clock(st.session_state["jam_masuk"]))
    slot["jam_defros"] = non_empty(normalize_clock(st.session_state["jam_defros"]))
    slot["jam_estimasi_defrost"] = non_empty(normalize_clock(st.session_state["jam_estimasi_defrost"]))
    slot["jam_estimasi_keluar"] = non_empty(normalize_clock(st.session_state["jam_estimasi_keluar"]))
    slot["jam_selesai_dry"] = non_empty(normalize_clock(st.session_state["jam_selesai_dry"]))
    slot["partial_out"] = st.session_state["partial_out"] == "yes"
    slot["jam_keluar_sebagian"] = non_empty(normalize_clock(st.session_state["jam_keluar_sebagian"]))
    slot["jam_estimasi_sisa"] = non_empty(normalize_clock(st.session_state["jam_estimasi_sisa"]))
    slot["partial_unload_content"] = non_empty(st.session_state["partial_unload_content"])
    slot["partial_unload_note"] = non_empty(st.session_state["partial_unload_note"])
    slot["jam_turun_packing"] = non_empty(normalize_clock(st.session_state["jam_turun_packing"]))
    slot["petugas_masuk"] = non_empty(st.session_state["petugas_masuk"])
    slot["petugas_keluar"] = non_empty(st.session_state["petugas_keluar"])
    slot["atas_izin"] = non_empty(st.session_state["atas_izin"])
    slot["notes"] = non_empty(st.session_state["notes"])

    if slot.get("jam_selesai_dry") and not slot.get("jam_turun_packing"):
        slot["status_enum"] = "SIAP_TURUN"
    if slot.get("jam_turun_packing"):
        slot["status_enum"] = "TURUN_PACKING"

    for date_key, time_key in [
        ("tgl_masuk", "jam_masuk"),
        ("tgl_defros", "jam_defros"),
        ("tgl_selesai_dry", "jam_selesai_dry"),
        ("tgl_turun_packing", "jam_turun_packing"),
    ]:
        if slot.get(time_key) and not slot.get(date_key):
            slot[date_key] = work_date

    save_draft()


def get_now_jakarta():
    now = datetime.now(ZoneInfo("Asia/Jakarta"))
    return now.date().isoformat(), now.strftime("%H:%M")


def fill_time_now(widget_key):
    st.session_state[widget_key] = get_now_jakarta()[1]


def set_feedback(message, ok=True):
    st.session_state["feedback_text"] = message
    st.session_state["feedback_ok"] = ok


def lock_time_once(slot, date_key, time_key):
    if slot.get(time_key):
        set_feedback(f"{time_key} slot No.{slot['slot_no']} sudah tercatat.", ok=False)
        return False
    today, clock = get_now_jakarta()
    slot[time_key] = clock
    slot[date_key] = slot.get(date_key) or today
    return True


def apply_quick_action(action):
    report = st.session_state["report"]
    slot = report["slots"][report["selected_slot"] - 1]

    if action == "masuk" and lock_time_once(slot, "tgl_masuk", "jam_masuk"):
        slot["status_enum"] = "PROSES"
    elif action == "defros" and lock_time_once(slot, "tgl_defros", "jam_defros"):
        slot["status_enum"] = "PROSES"
    elif action == "selesai" and lock_time_once(slot, "tgl_selesai_dry", "jam_selesai_dry"):
        if slot["status_enum"] != "TURUN_PACKING":
            slot["status_enum"] = "SIAP_TURUN"
    elif action == "selesai_tambahan" and lock_time_once(slot, "tgl_selesai_dry", "jam_selesai_dry"):
        slot["status_enum"] = "SIAP_TURUN"
    elif action == "lanjut_dry":
        slot["status_enum"] = "DRY_ULANG"
        slot["tgl_selesai_dry"] = None
        slot["jam_selesai_dry"] = None
        slot["tgl_turun_packing"] = None
        slot["jam_turun_packing"] = None
        slot["partial_out"] = False
        slot["jam_keluar_sebagian"] = None
        slot["partial_unload_content"] = None
        slot["partial_unload_note"] = None
    elif action == "turun_semua" and lock_time_once(slot, "tgl_turun_packing", "jam_turun_packing"):
        slot["status_enum"] = "TURUN_PACKING"
        slot["partial_out"] = False
        slot["jam_keluar_sebagian"] = None
        slot["partial_unload_content"] = None
        slot["partial_unload_note"] = None
    elif action == "turun" and lock_time_once(slot, "tgl_turun_packing", "jam_turun_packing"):
        slot["status_enum"] = "TURUN_PACKING"
    elif action == "kosong":
        if slot.get("jam_masuk") or slot.get("jam_defros") or slot.get("jam_selesai_dry") or slot.get("jam_turun_packing"):
            set_feedback("Slot ini sudah punya timestamp. Gunakan koreksi manual bila perlu.", ok=False)
            return
        slot["status_enum"] = "KOSONG"
    elif action == "tidak":
        if slot.get("jam_masuk") or slot.get("jam_defros") or slot.get("jam_selesai_dry") or slot.get("jam_turun_packing"):
            set_feedback("Slot ini sudah punya timestamp. Gunakan koreksi manual bila perlu.", ok=False)
            return
        slot["status_enum"] = "TIDAK_DIPAKAI"

    st.session_state["_pending_editor_sync"] = True
    save_draft()


def effective_defrost_required(slot):
    if isinstance(slot.get("needs_defrost"), bool):
        return slot["needs_defrost"]
    if slot.get("jam_defros") or slot.get("tgl_defros"):
        return True
    name = clean_text(slot.get("status_isi")).lower()
    if "dry ulang" in name:
        return False
    return True


def operator_state(slot):
    status = slot.get("status_enum")
    if status == "TIDAK_DIPAKAI":
        return "TIDAK_DIPAKAI"
    if status == "KOSONG":
        return "KOSONG"
    if status == "TURUN_PACKING" or slot.get("jam_turun_packing"):
        return "LAGI_KELUARKAN"
    if status == "DRY_ULANG":
        return "SEDANG_DRY_TAMBAHAN"
    if status in {"SIAP_TURUN", "SELESAI_DRY"} or (slot.get("jam_selesai_dry") and not slot.get("jam_turun_packing")):
        return "MENUNGGU_TURUN"
    if effective_defrost_required(slot) and (slot.get("jam_defros") or slot.get("tgl_defros")) and not slot.get("jam_masuk"):
        return "DEFROST"
    if slot.get("jam_masuk") or slot.get("tgl_masuk"):
        return "SEDANG_DRY"
    return "LAGI_ISI"


def state_helper_text(slot):
    state = operator_state(slot)
    if state == "MENUNGGU_TURUN":
        return "Dry selesai, pilih tindakan berikutnya."
    if state == "DEFROST":
        return "Lengkapi defrost lalu lanjut ke dry."
    if state == "SEDANG_DRY_TAMBAHAN":
        return "Tambahan dry sedang berjalan."
    if state == "LAGI_KELUARKAN":
        return "Proses turun packing sedang berjalan."
    return ""


def slot_group(slot):
    status = slot.get("status_enum")
    if status == "TIDAK_DIPAKAI":
        return "broken"
    if status == "KOSONG":
        return "nonactive"
    return "active"


def slot_group_label(slot):
    group = slot_group(slot)
    if group == "active":
        return "SLOT AKTIF"
    if group == "broken":
        return "TIDAK DIPAKAI"
    return "KOSONG"


def slot_state_label(slot):
    status = slot.get("status_enum")
    state = operator_state(slot)
    if state == "LAGI_KELUARKAN":
        return "Lagi Keluarkan"
    if state == "MENUNGGU_TURUN":
        return "Menunggu Turun"
    if state == "DEFROST":
        return "Defrost"
    if state == "SEDANG_DRY":
        return "Sedang Dry"
    if state == "SEDANG_DRY_TAMBAHAN":
        return "Sedang Dry Tambahan"
    if state == "LAGI_ISI":
        return "Lagi Isi"
    return STATUS_LABELS.get(status, status or "Kosong")


def clock_minutes(clock):
    normalized = normalize_clock(clock)
    if not normalized:
        return None
    hh, mm = normalized.split(":")
    return int(hh) * 60 + int(mm)


def format_duration(total_minutes):
    minutes = max(0, int(total_minutes))
    hours = minutes // 60
    rest = minutes % 60
    if hours <= 0:
        return f"{rest}m"
    if rest == 0:
        return f"{hours}j"
    return f"{hours}j {rest}m"


def target_clock(slot):
    if operator_state(slot) == "DEFROST" and effective_defrost_required(slot):
        return slot.get("jam_estimasi_defrost") or ""
    return slot.get("jam_estimasi_keluar") or ""


def start_clock(slot):
    if operator_state(slot) == "DEFROST":
        return slot.get("jam_defros") or ""
    return slot.get("jam_masuk") or slot.get("jam_selesai_dry") or ""


def elapsed_or_remaining(slot):
    now_minutes = clock_minutes(get_now_jakarta()[1])
    target = clock_minutes(target_clock(slot))
    start = clock_minutes(start_clock(slot))
    if target is not None:
        diff = target - now_minutes
        prefix = "Sisa" if diff >= 0 else "Lewat"
        return f"{prefix} {format_duration(abs(diff))}"
    if start is not None:
        return f"Jalan {format_duration(max(0, now_minutes - start))}"
    return "Belum ada jam"


def current_action_type(slot):
    status = slot.get("status_enum")
    state = operator_state(slot)
    now_minutes = clock_minutes(get_now_jakarta()[1])
    if state == "DEFROST" and target_clock(slot) and clock_minutes(target_clock(slot)) is not None:
        if now_minutes >= clock_minutes(target_clock(slot)):
            return "MULAI DRY"
    if state == "MENUNGGU_TURUN":
        return "PILIH_TINDAKAN"
    if state in {"SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"}:
        return "SELESAI_SETTING"
    if state == "LAGI_ISI":
        return "MULAI_DEFROST" if effective_defrost_required(slot) else "MULAI_DRY"
    return ""


def action_type_badge(slot):
    action = current_action_type(slot)
    return f"AKSI: {action}" if action else ""


def action_priority_text(slot):
    action = current_action_type(slot)
    if action == "PILIH_TINDAKAN":
        return "Pilih Lanjut Dry atau Turun Semua"
    if action == "MULAI_DRY":
        return "Mulai dry sekarang"
    if action == "MULAI_DEFROST":
        return "Mulai defrost terlebih dahulu"
    if action == "SELESAI_SETTING":
        return "Simpan jam selesai setting dry"
    if action == "LANJUT_DRY":
        return "Lanjut dry tambahan atau kembali ke Menunggu Turun"
    return "Cek slot sesuai perubahan terakhir"


def slot_update_type(slot):
    if any(clean_text(slot.get(key)) for key in ["jam_masuk", "jam_defros", "jam_selesai_dry", "status_isi"]) and not slot.get("jam_turun_packing"):
        return "Lanjutan shift sebelumnya"
    if slot.get("status_enum") in {"KOSONG", "TIDAK_DIPAKAI"}:
        return "Update shift saya"
    return "Cek perubahan shift saya"


def compact_slot_list(slots):
    if not slots:
        return "-"
    labels = [f"No.{slot['slot_no']}" for slot in slots[:6]]
    if len(slots) > 6:
        labels.append(f"+{len(slots) - 6}")
    return ", ".join(labels)


def product_label(slot):
    return clean_text(slot.get("status_isi")) or "-"


def short_context_text(slot):
    helper = state_helper_text(slot)
    if helper:
        return helper
    action = current_action_type(slot)
    if action:
        return action_priority_text(slot)
    return slot_state_label(slot)


def passive_slot_text(slot):
    return slot_state_label(slot)


def summary_item_markup(slot, emphasize_action=False):
    title = f"No.{slot['slot_no']} | {product_label(slot)}"
    shift_line = slot_update_type(slot)
    timing = elapsed_or_remaining(slot)
    context = action_priority_text(slot) if emphasize_action else short_context_text(slot)
    action_badge = ""
    if emphasize_action and current_action_type(slot):
        action_badge = f'<div class="sd-mini-badge">{html.escape(action_type_badge(slot))}</div>'
    return (
        '<div class="sd-mini-card">'
        f"{action_badge}"
        f'<div class="sd-mini-title">{html.escape(title)}</div>'
        f'<div class="sd-mini-meta">{html.escape(shift_line)}</div>'
        f'<div class="sd-mini-time">{html.escape(timing)}</div>'
        f'<div class="sd-mini-action">{html.escape(context)}</div>'
        "</div>"
    )


def board_card_markup(slot):
    product = product_label(slot)
    state = slot_state_label(slot)
    timing = elapsed_or_remaining(slot)
    check_now = action_priority_text(slot) if current_action_type(slot) else short_context_text(slot)
    tone = " action" if current_action_type(slot) else (" passive" if slot_group(slot) != "active" else "")
    badge = action_type_badge(slot) if current_action_type(slot) else slot_group_label(slot)
    return (
        f'<div class="sd-board-card{tone}">'
        f'<div class="sd-board-badge">{html.escape(badge)}</div>'
        f'<div class="sd-board-slot">No.{slot["slot_no"]}</div>'
        f'<div class="sd-board-product">{html.escape(product if product != "-" else "Belum ada produk")}</div>'
        f'<div class="sd-board-state">{html.escape(state)}</div>'
        f'<div class="sd-board-time">{html.escape(timing)}</div>'
        f'<div class="sd-board-check">{html.escape(check_now)}</div>'
        "</div>"
    )


def quick_action_primary(slot):
    state = operator_state(slot)
    if state in {"KOSONG", "LAGI_ISI"}:
        return "defros" if effective_defrost_required(slot) else "masuk"
    if state == "DEFROST":
        return "masuk"
    if state == "SEDANG_DRY":
        return "selesai"
    if state == "SEDANG_DRY_TAMBAHAN":
        return "selesai_tambahan"
    return ""


def quick_action_label(action):
    return {
        "masuk": "Mulai Dry",
        "defros": "Mulai Defrost",
        "selesai": "Selesai Setting Dry",
        "selesai_tambahan": "Selesai Dry Tambahan",
        "lanjut_dry": "Lanjut Dry",
        "turun_semua": "Turun Semua",
        "kosong": "Set kosong",
        "tidak": "Set tidak dipakai",
    }.get(action, "")


def quick_action_disabled_reason(slot, action):
    if action in {"defros", "masuk"} and product_label(slot) == "-":
        return "Isi produk dulu sebelum mulai dry."
    if action in {"lanjut_dry", "turun_semua"} and not clean_text(slot.get("jam_selesai_dry")):
        return "Jam Selesai Setting Dry belum tercatat."
    return ""


def visible_quick_actions(slot):
    primary = quick_action_primary(slot)
    if operator_state(slot) == "MENUNGGU_TURUN":
        return ["lanjut_dry", "turun_semua"]
    return [primary] if primary else []


def available_danger_actions(slot):
    has_history = any(
        clean_text(slot.get(key))
        for key in ["jam_masuk", "jam_defros", "jam_selesai_dry", "jam_turun_packing"]
    )
    if has_history:
        return []
    return ["kosong", "tidak"]


def payload_from_state():
    sync_report_from_widgets()
    payload = deepcopy(st.session_state["report"])
    work_date = payload["report_meta"]["prd_date"]
    payload["selected_slot"] = payload.get("selected_slot") or st.session_state["report"]["selected_slot"]
    payload["report_meta"]["submitted_at_system"] = datetime.utcnow().isoformat()
    for slot in payload["slots"]:
        for date_key, time_key in [
            ("tgl_masuk", "jam_masuk"),
            ("tgl_defros", "jam_defros"),
            ("tgl_selesai_dry", "jam_selesai_dry"),
            ("tgl_turun_packing", "jam_turun_packing"),
        ]:
            if slot.get(time_key) and not slot.get(date_key):
                slot[date_key] = work_date
    return payload


def get_state():
    try:
        return api_json(LOCAL_STATE_URL).get("state", {})
    except Exception:
        return {}


def sync_lock_from_server(server_state):
    team_id = st.session_state.get("team_id", "dry-team-1")
    work_date = (
        st.session_state["work_date"].isoformat()
        if isinstance(st.session_state.get("work_date"), date)
        else clean_text(st.session_state.get("work_date"))
    )
    lock_key = f"{team_id}__{work_date}"
    lock = (server_state.get("team_locks") or {}).get(lock_key)
    if lock:
        st.session_state["lock"] = lock


def open_team(takeover=False):
    payload = {
        "teamId": st.session_state["team_id"],
        "workDate": st.session_state["work_date"].isoformat(),
        "lockOwner": st.session_state["lock_owner"] or "operator",
    }
    url = f"{LOCAL_APP_URL}/api/takeover" if takeover else f"{LOCAL_APP_URL}/api/open"
    result = api_json(url, method="POST", payload=payload)
    lock = result.get("lock")
    st.session_state["lock"] = lock
    set_feedback("Tim berhasil diambil alih." if takeover else "Tim berhasil dibuka.", ok=True)


def retry_pending():
    result = api_json(f"{LOCAL_APP_URL}/api/retry", method="POST", payload={})
    entries = result.get("result", [])
    failed = [entry for entry in entries if entry.get("status") != "success"]
    set_feedback("Retry selesai, sebagian masih gagal." if failed else "Retry berhasil.", ok=not failed)


def submit_report():
    payload = payload_from_state()
    lock = st.session_state.get("lock") or {}
    body = {
        "payload": payload,
        "teamId": st.session_state["team_id"],
        "workDate": st.session_state["work_date"].isoformat(),
        "lockOwner": st.session_state["lock_owner"] or "operator",
        "lockToken": lock.get("lockToken", ""),
        "expectedVersion": int(lock.get("version", 1)),
    }
    result = api_json(f"{LOCAL_APP_URL}/api/submit", method="POST", payload=body)
    message = result.get("result", {}).get("message") or "Berhasil dikirim."
    set_feedback(message, ok=result.get("result", {}).get("status") != "failed")
    save_draft()


def select_slot(slot_no: int):
    st.session_state["report"]["selected_slot"] = slot_no
    st.session_state["_pending_editor_sync"] = True


def render_summary():
    slots = st.session_state["report"]["slots"]
    action_slots = [slot for slot in slots if current_action_type(slot)]
    active_slots = [slot for slot in slots if slot_group(slot) == "active" and not current_action_type(slot)]
    nonactive_slots = [slot for slot in slots if slot_group(slot) == "nonactive"]
    broken_slots = [slot for slot in slots if slot_group(slot) == "broken"]

    st.markdown("### Ringkasan cepat")

    with st.container(border=True):
        st.markdown(
            f'<div class="sd-section-head strong"><span>PERLU AKSI</span><strong>{len(action_slots)}</strong></div>',
            unsafe_allow_html=True,
        )
        if action_slots:
            st.markdown(
                "".join(summary_item_markup(slot, emphasize_action=True) for slot in action_slots[:4]),
                unsafe_allow_html=True,
            )
            if len(action_slots) > 4:
                st.caption(f"+{len(action_slots) - 4} slot lain perlu dicek")
        else:
            st.caption("Belum ada slot yang perlu dicek sekarang.")

    with st.container(border=True):
        st.markdown(
            f'<div class="sd-section-head"><span>SLOT AKTIF</span><strong>{len(active_slots)}</strong></div>',
            unsafe_allow_html=True,
        )
        if active_slots:
            st.markdown(
                "".join(summary_item_markup(slot, emphasize_action=False) for slot in active_slots[:4]),
                unsafe_allow_html=True,
            )
            if len(active_slots) > 4:
                st.caption(f"+{len(active_slots) - 4} slot aktif lain")
        else:
            st.caption("Tidak ada slot aktif lain.")

    st.markdown(
        f"""
        <div class="sd-passive-bar">
          <div><strong>KOSONG ({len(nonactive_slots)})</strong><span>{html.escape(compact_slot_list(nonactive_slots))}</span></div>
          <div><strong>TIDAK DIPAKAI ({len(broken_slots)})</strong><span>{html.escape(compact_slot_list(broken_slots))}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_board():
    st.markdown("### Papan slot dry")
    slots = st.session_state["report"]["slots"]
    ordered_slots = sorted(
        slots,
        key=lambda slot: (
            0 if current_action_type(slot) else 1,
            0 if slot_group(slot) == "active" else 1,
            slot["slot_no"],
        ),
    )
    cols = st.columns(2)
    for idx, slot in enumerate(ordered_slots):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(board_card_markup(slot), unsafe_allow_html=True)
                if st.button(f"Buka No.{slot['slot_no']}", key=f"slot_btn_{slot['slot_no']}", use_container_width=True):
                    select_slot(slot["slot_no"])
                    st.rerun()


def render_time_input_row(label, widget_key):
    input_col, button_col = st.columns([4, 1])
    with input_col:
        st.text_input(label, key=widget_key, placeholder="HH:mm")
    with button_col:
        st.write("")
        st.button(
            "Sekarang",
            key=f"{widget_key}_now",
            use_container_width=True,
            on_click=fill_time_now,
            args=(widget_key,),
        )


def field_visibility(slot):
    state = operator_state(slot)
    has_product_context = bool(
        product_label(slot) != "-"
        or slot.get("jam_masuk")
        or slot.get("jam_defros")
        or slot.get("jam_selesai_dry")
        or slot.get("jam_turun_packing")
    )
    return {
        "jam_defros": state == "DEFROST" or (state == "LAGI_ISI" and effective_defrost_required(slot)) or bool(slot.get("jam_defros")),
        "jam_masuk": state in {"LAGI_ISI", "SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"} and has_product_context,
        "jam_selesai_dry": state in {"SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"} and bool(slot.get("jam_masuk") or slot.get("jam_selesai_dry")),
        "jam_turun_packing": state in {"MENUNGGU_TURUN", "LAGI_KELUARKAN"} or bool(slot.get("jam_turun_packing")),
        "estimasi_defrost": state in {"LAGI_ISI", "DEFROST"} and effective_defrost_required(slot) and not slot.get("jam_masuk"),
        "estimasi_keluar": state in {"SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"} and bool(slot.get("jam_masuk") or slot.get("jam_estimasi_keluar")),
        "partial_log": False,
        "personnel": state not in {"KOSONG", "TIDAK_DIPAKAI"},
    }


def saved_value_lines(slot):
    lines = []
    mapping = [
        ("Jam Defrost", slot.get("jam_defros")),
        ("Jam Masuk", slot.get("jam_masuk")),
        ("Jam Selesai Setting Dry", slot.get("jam_selesai_dry")),
        ("Jam Turun Packing", slot.get("jam_turun_packing")),
    ]
    for label, value in mapping:
        if clean_text(value):
            lines.append(f"{label}: {value}")
    return lines


def render_saved_summary(slot):
    next_action = action_priority_text(slot) if current_action_type(slot) else "Tidak ada tindakan lanjutan sekarang."
    values = saved_value_lines(slot)
    value_text = "<br/>".join(html.escape(line) for line in values) if values else "Belum ada nilai waktu yang tersimpan."
    st.markdown(
        f"""
        <div class="sd-saved-box">
          <div class="sd-saved-title">Tersimpan untuk slot ini</div>
          <div class="sd-saved-row"><strong>Status sekarang</strong><span>{html.escape(slot_state_label(slot))}</span></div>
          <div class="sd-saved-row"><strong>Nilai tersimpan</strong><span>{value_text}</span></div>
          <div class="sd-saved-row"><strong>Langkah berikut</strong><span>{html.escape(next_action)}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_readonly_summary(label, value):
    st.text_input(label, value=clean_text(value), disabled=True)


def render_detail():
    sync_editor_widgets_from_selected_slot()
    report = st.session_state["report"]
    slot = report["slots"][report["selected_slot"] - 1]
    visibility = field_visibility(slot)
    state = operator_state(slot)
    st.markdown("### Detail slot")
    st.markdown(
        f"""
        <div class="sd-detail-head">
          <strong>No.{slot['slot_no']} | {html.escape(product_label(slot))}</strong>
          <span>{html.escape(slot_state_label(slot))}</span>
          <span>{html.escape(state_helper_text(slot) or slot_update_type(slot))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    actions = visible_quick_actions(slot)
    if actions:
        action_cols = st.columns(max(1, len(actions)))
        for idx, action in enumerate(actions):
            with action_cols[idx]:
                disabled_reason = quick_action_disabled_reason(slot, action)
                if st.button(
                    quick_action_label(action),
                    key=f"qa_{action}",
                    type="primary",
                    use_container_width=True,
                    disabled=bool(disabled_reason),
                ):
                    apply_quick_action(action)
                    st.rerun()
                if disabled_reason:
                    st.caption(disabled_reason)

    danger_actions = available_danger_actions(slot)
    if danger_actions:
        with st.expander("Aksi berisiko", expanded=False):
            risk_cols = st.columns(len(danger_actions))
            for idx, action in enumerate(danger_actions):
                with risk_cols[idx]:
                    if st.button(quick_action_label(action), key=f"risk_{action}", use_container_width=True):
                        apply_quick_action(action)
                        st.rerun()

    with st.expander("Info produk / rule", expanded=True):
        st.text_input("Produk di Slot", key="status_isi")
        st.selectbox("Defrost Diperlukan?", options=["yes", "no"], format_func=lambda x: "Ya, perlu defrost" if x == "yes" else "Tidak perlu defrost", key="needs_defrost")
        if st.session_state["needs_defrost"] == "no":
            if slot.get("jam_defros") or slot.get("tgl_defros"):
                st.info("Defrost tidak diperlukan lagi, tetapi catatan defrost lama tetap tersimpan.")
            else:
                st.info("Jalur slot ini tanpa defrost.")

    with st.expander("Catatan waktu / detail record", expanded=False):
        st.caption("Lengkapi hanya field yang memang dipakai pada status sekarang.")
        if state == "MENUNGGU_TURUN":
            st.markdown("**Dry selesai, pilih tindakan berikutnya**")
            s1, s2 = st.columns(2)
            with s1:
                render_readonly_summary("Jam Masuk", slot.get("jam_masuk"))
            with s2:
                render_readonly_summary("Jam Selesai Setting Dry", slot.get("jam_selesai_dry"))
        c1, c2 = st.columns(2)
        with c1:
            if visibility["jam_defros"] and state in {"LAGI_ISI", "DEFROST"}:
                render_time_input_row("Jam Defrost", "jam_defros")
            if visibility["jam_masuk"] and state in {"LAGI_ISI", "SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"}:
                render_time_input_row("Jam Masuk", "jam_masuk")
            if visibility["estimasi_defrost"] and st.session_state["needs_defrost"] == "yes":
                st.text_input("Estimasi Selesai Defrost", key="jam_estimasi_defrost", placeholder="HH:mm")
            if visibility["jam_selesai_dry"] and state in {"SEDANG_DRY", "SEDANG_DRY_TAMBAHAN"}:
                render_time_input_row("Jam Selesai Setting Dry", "jam_selesai_dry")
            if visibility["estimasi_keluar"] and state in {"SEDANG_DRY", "MENUNGGU_TURUN", "SEDANG_DRY_TAMBAHAN"}:
                st.text_input("Estimasi Keluar", key="jam_estimasi_keluar", placeholder="HH:mm")
        with c2:
            if visibility["jam_turun_packing"] and state in {"MENUNGGU_TURUN", "LAGI_KELUARKAN"}:
                render_time_input_row("Jam Turun Packing", "jam_turun_packing")

        if visibility["personnel"]:
            st.text_input("Petugas Masuk", key="petugas_masuk")
            st.text_input("Petugas Keluar", key="petugas_keluar")
            st.text_input("Atas Izin", key="atas_izin")
        st.text_input("Catatan", key="notes")

    sync_report_from_widgets()
    render_saved_summary(report["slots"][report["selected_slot"] - 1])


def render_header_controls(server_state):
    st.markdown("## Status Dry")
    st.caption("Lanjutkan status sebelumnya, lalu ubah hanya slot yang benar-benar berubah.")
    security = server_state.get("security", {})
    if security.get("app_locked"):
        st.error(security.get("reason") or "Aplikasi terkunci.")

    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.date_input("Tgl Produksi", key="work_date")
        with col2:
            st.selectbox("Shift", ["Shift 1", "Shift 2", "Shift 3"], key="shift")
        with col3:
            st.text_input("Pelapor", key="lock_owner")

        with st.expander("Info tim tambahan (opsional)", expanded=False):
            st.text_input("Anggota Tim", key="members", help="Pisahkan dengan koma")
            row1, row2 = st.columns(2)
            with row1:
                st.text_input("Tim Berikutnya / Handover", key="team_finish")
            with row2:
                st.text_input("Jam Handover", key="handover_time", placeholder="HH:mm")

        if st.button("Buka Tim", use_container_width=True):
            try:
                open_team(False)
                st.rerun()
            except Exception as err:
                set_feedback(str(err), ok=False)


def render_feedback():
    text = clean_text(st.session_state.get("feedback_text"))
    if not text:
        return
    if st.session_state.get("feedback_ok", True):
        st.success(text)
    else:
        st.error(text)


def render_submit():
    st.markdown("---")
    if st.button("Kirim Update", type="primary", use_container_width=True):
        try:
            submit_report()
            st.rerun()
        except Exception as err:
            set_feedback(str(err), ok=False)
            st.rerun()
    render_feedback()


def main():
    st.set_page_config(page_title="Status Dry", page_icon="🧾", layout="centered")
    st.markdown(
        """
        <style>
        .block-container {
          max-width: 980px;
          padding-top: 1.2rem;
          padding-bottom: 3rem;
        }
        .stButton button {
          min-height: 46px;
          border-radius: 12px;
          font-weight: 700;
        }
        .stCaption { line-height: 1.35; }
        .sd-section-head {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 8px;
        }
        .sd-section-head span {
          font-size: 0.88rem;
          font-weight: 800;
          color: #516377;
        }
        .sd-section-head strong {
          font-size: 1.2rem;
          color: #142132;
        }
        .sd-section-head.strong strong { color: #8d6200; }
        .sd-mini-card {
          border: 1px solid #d8e2eb;
          border-radius: 14px;
          background: #fbfdff;
          padding: 10px 11px;
          margin-top: 8px;
        }
        .sd-mini-title {
          font-size: 0.98rem;
          font-weight: 800;
          color: #142132;
        }
        .sd-mini-meta, .sd-mini-time {
          margin-top: 4px;
          font-size: 0.84rem;
          color: #526476;
        }
        .sd-mini-action {
          margin-top: 6px;
          font-size: 0.88rem;
          font-weight: 700;
          color: #6c4b00;
        }
        .sd-mini-badge {
          display: inline-block;
          margin-bottom: 6px;
          padding: 3px 8px;
          border-radius: 999px;
          background: #fff3d6;
          border: 1px solid #ebcd88;
          color: #7d5500;
          font-size: 0.72rem;
          font-weight: 900;
        }
        .sd-mini-state {
          margin-top: 6px;
          font-size: 0.78rem;
          font-weight: 800;
          color: #0f6c5a;
        }
        .sd-passive-bar {
          display: grid;
          gap: 8px;
          margin-top: 10px;
        }
        .sd-passive-bar > div {
          display: flex;
          align-items: baseline;
          gap: 8px;
          border: 1px solid #dbe3ea;
          border-radius: 11px;
          padding: 8px 10px;
          background: #f8fbfd;
          font-size: 0.84rem;
        }
        .sd-passive-bar strong {
          flex: 0 0 auto;
          color: #334456;
        }
        .sd-passive-bar span {
          color: #596b7d;
          font-weight: 700;
        }
        .sd-board-card {
          border-left: 5px solid #2a70d1;
          border-radius: 14px;
          background: #ffffff;
          padding: 10px 12px 8px;
          margin-bottom: 10px;
          box-shadow: inset 0 0 0 1px #d7e1eb;
        }
        .sd-board-card.action {
          border-left-color: #d79a05;
          box-shadow: inset 0 0 0 2px #f0c456;
        }
        .sd-board-card.passive {
          border-left-color: #a1adba;
          background: #f9fbfd;
        }
        .sd-board-badge {
          display: inline-block;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 0.72rem;
          font-weight: 900;
          background: #eef4fb;
          color: #39577a;
          border: 1px solid #d4dfea;
        }
        .sd-board-card.action .sd-board-badge {
          background: #fff3d6;
          color: #7d5500;
          border-color: #ebcd88;
        }
        .sd-board-slot {
          margin-top: 9px;
          font-size: 1.1rem;
          font-weight: 900;
          color: #142132;
        }
        .sd-board-product {
          margin-top: 6px;
          font-size: 1rem;
          font-weight: 800;
          color: #142132;
        }
        .sd-board-state {
          margin-top: 7px;
          font-size: 0.88rem;
          font-weight: 800;
          color: #24435e;
        }
        .sd-board-time {
          margin-top: 4px;
          font-size: 0.84rem;
          color: #536476;
        }
        .sd-board-check {
          margin-top: 7px;
          font-size: 0.86rem;
          font-weight: 700;
          color: #6c4b00;
        }
        .sd-detail-head {
          display: grid;
          gap: 4px;
          margin-bottom: 10px;
        }
        .sd-detail-head strong {
          font-size: 1rem;
          color: #142132;
        }
        .sd-detail-head span {
          font-size: 0.85rem;
          color: #536476;
        }
        .sd-saved-box {
          margin-top: 12px;
          border: 1px solid #d7e0e8;
          border-radius: 14px;
          background: #f8fbfd;
          padding: 11px 12px;
        }
        .sd-saved-title {
          font-size: 0.86rem;
          font-weight: 900;
          color: #39577a;
          margin-bottom: 8px;
        }
        .sd-saved-row {
          display: grid;
          gap: 4px;
          margin-top: 8px;
        }
        .sd-saved-row strong {
          font-size: 0.8rem;
          color: #526476;
        }
        .sd-saved-row span {
          font-size: 0.9rem;
          font-weight: 700;
          color: #162536;
          line-height: 1.35;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    apply_streamlit_secrets()
    ok, state = ensure_server()
    if not ok:
        st.error("Backend dry belum siap.")
        if state == "missing_node":
            st.error("Node.js tidak ditemukan di environment ini.")
        else:
            st.warning("Server internal belum berhasil start. Refresh sebentar lagi.")
        return

    ensure_app_state()
    sync_header_widgets_from_report()
    server_state = get_state()
    sync_lock_from_server(server_state)

    render_header_controls(server_state)
    st.markdown("---")
    render_summary()
    st.markdown("---")
    render_board()
    st.markdown("---")
    render_detail()
    render_submit()


if __name__ == "__main__":
    main()
