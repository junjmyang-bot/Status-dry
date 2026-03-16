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
    "PROSES": "Sedang diproses",
    "SIAP_TURUN": "Siap turun",
    "SELESAI_DRY": "Selesai dry",
    "TURUN_PACKING": "Sudah turun ke packing",
    "DRY_ULANG": "Dry ulang",
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
        sync_widgets_from_report()


def sync_widgets_from_report():
    report = st.session_state["report"]
    meta = report["report_meta"]
    team_start = meta["team_start"]
    slot = report["slots"][report["selected_slot"] - 1]

    st.session_state["work_date"] = datetime.strptime(meta["prd_date"], "%Y-%m-%d").date()
    st.session_state["shift"] = team_start.get("shift") or "Shift 1"
    st.session_state["members"] = ", ".join(team_start.get("members") or [])
    st.session_state["team_finish"] = clean_text(meta.get("team_finish"))
    st.session_state["handover_time"] = clean_text(meta.get("handover_time"))
    st.session_state["team_id"] = st.session_state.get("team_id", "dry-team-1")
    st.session_state["lock_owner"] = st.session_state.get("lock_owner") or (split_names(st.session_state["members"])[0] if split_names(st.session_state["members"]) else "operator")

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
    st.session_state["jam_turun_packing"] = clean_text(slot.get("jam_turun_packing"))
    st.session_state["petugas_masuk"] = clean_text(slot.get("petugas_masuk"))
    st.session_state["petugas_keluar"] = clean_text(slot.get("petugas_keluar"))
    st.session_state["atas_izin"] = clean_text(slot.get("atas_izin"))
    st.session_state["notes"] = clean_text(slot.get("notes"))


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
    slot["jam_turun_packing"] = non_empty(normalize_clock(st.session_state["jam_turun_packing"]))
    slot["petugas_masuk"] = non_empty(st.session_state["petugas_masuk"])
    slot["petugas_keluar"] = non_empty(st.session_state["petugas_keluar"])
    slot["atas_izin"] = non_empty(st.session_state["atas_izin"])
    slot["notes"] = non_empty(st.session_state["notes"])

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

    sync_widgets_from_report()
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


def process_stage(slot):
    if slot.get("status_enum") != "PROSES":
        return ""
    if effective_defrost_required(slot) and (slot.get("jam_defros") or slot.get("tgl_defros")):
        return "DEFROST"
    if slot.get("jam_masuk") or slot.get("tgl_masuk"):
        return "LAGI_DIISI"
    return "PROSES"


def slot_group(slot):
    status = slot.get("status_enum")
    if status == "TIDAK_DIPAKAI":
        return "broken"
    if status in {"KOSONG", "TURUN_PACKING"}:
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
    if slot.get("partial_out"):
        return "SEBAGIAN KELUAR, SISA MASIH DRY"
    status = slot.get("status_enum")
    if status == "PROSES":
        stage = process_stage(slot)
        if stage == "DEFROST":
            return "Defrost"
        if stage == "LAGI_DIISI":
            return "Lagi diisi"
        return "Sedang dry"
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
    if process_stage(slot) == "DEFROST" and effective_defrost_required(slot):
        return slot.get("jam_estimasi_defrost") or ""
    if slot.get("partial_out") and slot.get("jam_estimasi_sisa"):
        return slot.get("jam_estimasi_sisa")
    return slot.get("jam_estimasi_keluar") or ""


def start_clock(slot):
    return slot.get("jam_defros") or slot.get("jam_masuk") or ""


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
    now_minutes = clock_minutes(get_now_jakarta()[1])
    if process_stage(slot) == "DEFROST" and target_clock(slot) and clock_minutes(target_clock(slot)) is not None:
        if now_minutes >= clock_minutes(target_clock(slot)):
            return "MULAI DRY"
    if status == "SIAP_TURUN":
        return "KELUARKAN"
    if status == "SELESAI_DRY" and not slot.get("jam_turun_packing"):
        return "KELUARKAN"
    if status in {"PROSES", "DRY_ULANG"} and target_clock(slot):
        if now_minutes >= clock_minutes(target_clock(slot)) - 30:
            return "CEK DRY"
    return ""


def action_type_badge(slot):
    action = current_action_type(slot)
    return f"AKSI: {action}" if action else ""


def action_priority_text(slot):
    action = current_action_type(slot)
    if action == "CEK DRY":
        return "Cek apakah dry sudah selesai"
    if action == "KELUARKAN":
        return "Cek apakah barang sudah turun ke packing"
    if action == "MULAI DRY":
        return "Mulai dry setelah defrost" if effective_defrost_required(slot) else "Mulai dry sekarang"
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
    if slot.get("partial_out"):
        return "Sebagian keluar"
    action = current_action_type(slot)
    if action:
        return action_priority_text(slot)
    return slot_state_label(slot)


def quick_action_primary(slot):
    status = slot.get("status_enum")
    if status == "KOSONG":
        return "defros" if effective_defrost_required(slot) and not slot.get("jam_defros") else "masuk"
    if status == "PROSES" and effective_defrost_required(slot) and not slot.get("jam_defros") and process_stage(slot) != "DEFROST":
        return "defros"
    if status in {"PROSES", "DRY_ULANG"}:
        return "selesai"
    if status in {"SIAP_TURUN", "SELESAI_DRY"}:
        return "turun"
    return ""


def quick_action_label(action):
    return {
        "masuk": "Mulai Dry",
        "defros": "Mulai Defrost",
        "selesai": "Selesai Dry",
        "turun": "Keluarkan ke Packing",
        "kosong": "Set kosong",
        "tidak": "Set tidak dipakai",
    }.get(action, "")


def visible_quick_actions(slot):
    primary = quick_action_primary(slot)
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
    sync_widgets_from_report()


def render_summary():
    slots = st.session_state["report"]["slots"]
    groups = {
        "active": [slot for slot in slots if slot_group(slot) == "active"],
        "action": [slot for slot in slots if current_action_type(slot)],
        "nonactive": [slot for slot in slots if slot_group(slot) == "nonactive"],
        "broken": [slot for slot in slots if slot_group(slot) == "broken"],
    }

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.caption("PERLU AKSI")
            st.subheader(str(len(groups["action"])))
            if groups["action"]:
                for slot in groups["action"][:3]:
                    st.markdown(
                        f"**No.{slot['slot_no']} | {product_label(slot)}**  \n"
                        f"**{action_type_badge(slot)}**  \n"
                        f"{elapsed_or_remaining(slot)}  \n"
                        f"{action_priority_text(slot)}"
                    )
                    if slot.get("partial_out"):
                        st.caption("SEBAGIAN KELUAR, SISA MASIH DRY")
                if len(groups["action"]) > 3:
                    st.caption(f"+{len(groups['action']) - 3} slot lain")
            else:
                st.write("-")
    with col2:
        with st.container(border=True):
            st.caption("SLOT AKTIF")
            st.subheader(str(len(groups["active"])))
            if groups["active"]:
                for slot in groups["active"][:3]:
                    st.markdown(
                        f"**No.{slot['slot_no']} | {product_label(slot)}**  \n"
                        f"{elapsed_or_remaining(slot)}  \n"
                        f"{short_context_text(slot)}"
                    )
                if len(groups["active"]) > 3:
                    st.caption(f"+{len(groups['active']) - 3} slot lain")
            else:
                st.write("-")

    st.caption(
        f"KOSONG ({len(groups['nonactive'])}): {compact_slot_list(groups['nonactive'])} | "
        f"TIDAK DIPAKAI ({len(groups['broken'])}): {compact_slot_list(groups['broken'])}"
    )


def render_board():
    st.subheader("Papan slot dry")
    slots = st.session_state["report"]["slots"]
    cols = st.columns(2)
    for idx, slot in enumerate(slots):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(f"**No.{slot['slot_no']}**")
                st.markdown(f"**{(product_label(slot) if product_label(slot) != '-' else 'Belum ada produk').upper()}**")
                st.caption(slot_state_label(slot))
                st.caption(elapsed_or_remaining(slot))
                if current_action_type(slot):
                    st.warning(action_priority_text(slot))
                if st.button(f"Buka No.{slot['slot_no']}", key=f"slot_btn_{slot['slot_no']}", use_container_width=True):
                    select_slot(slot["slot_no"])
                    st.rerun()


def render_detail():
    report = st.session_state["report"]
    slot = report["slots"][report["selected_slot"] - 1]
    st.subheader(f"Detail Slot No.{slot['slot_no']}")
    st.caption(f"{slot_state_label(slot)} | {slot_update_type(slot)}")

    actions = visible_quick_actions(slot)
    if actions:
        action_cols = st.columns(len(actions))
        for idx, action in enumerate(actions):
            with action_cols[idx]:
                if st.button(quick_action_label(action), key=f"qa_{action}", type="primary", use_container_width=True):
                    apply_quick_action(action)
                    st.rerun()
    else:
        st.caption("Tidak ada aksi cepat untuk slot ini.")

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
        if slot.get("partial_out"):
            st.warning("SEBAGIAN KELUAR, SISA MASIH DRY")

    with st.expander("Catatan waktu / detail record", expanded=False):
        st.caption("Bagian ini untuk melengkapi catatan. Status papan tetap mengikuti aksi cepat.")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Jam Masuk", key="jam_masuk", placeholder="HH:mm")
            if st.session_state["needs_defrost"] == "yes":
                st.text_input("Jam Defrost", key="jam_defros", placeholder="HH:mm")
                st.text_input("Estimasi Selesai Defrost", key="jam_estimasi_defrost", placeholder="HH:mm")
            st.text_input("Estimasi Keluar", key="jam_estimasi_keluar", placeholder="HH:mm")
            st.text_input("Jam Selesai Dry", key="jam_selesai_dry", placeholder="HH:mm")
        with c2:
            st.selectbox("Sebagian Keluar?", options=["no", "yes"], format_func=lambda x: "Ya" if x == "yes" else "Tidak", key="partial_out")
            if st.session_state["partial_out"] == "yes":
                st.text_input("Jam Keluar Sebagian", key="jam_keluar_sebagian", placeholder="HH:mm")
                st.text_input("Estimasi Selesai Sisa", key="jam_estimasi_sisa", placeholder="HH:mm")
            st.text_input("Jam Turun Packing", key="jam_turun_packing", placeholder="HH:mm")

        st.text_input("Petugas Masuk", key="petugas_masuk")
        st.text_input("Petugas Keluar", key="petugas_keluar")
        st.text_input("Atas Izin", key="atas_izin")
        st.text_input("Catatan", key="notes")

    sync_report_from_widgets()


def render_header_controls(server_state):
    st.title("Status Dry")
    security = server_state.get("security", {})
    if security.get("app_locked"):
        st.error(security.get("reason") or "Aplikasi terkunci.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.date_input("Tgl Produksi", key="work_date")
    with col2:
        st.selectbox("Shift", ["Shift 1", "Shift 2", "Shift 3"], key="shift")
    with col3:
        st.text_input("Pelapor", key="lock_owner")

    st.text_input("Anggota Tim", key="members", help="Pisahkan dengan koma")
    row1, row2 = st.columns(2)
    with row1:
        st.text_input("Tim Berikutnya / Handover", key="team_finish")
    with row2:
        st.text_input("Jam Handover", key="handover_time", placeholder="HH:mm")

    controls = st.columns(2)
    with controls[0]:
        if st.button("Buka Tim", use_container_width=True):
            try:
                open_team(False)
                st.rerun()
            except Exception as err:
                set_feedback(str(err), ok=False)
    with controls[1]:
        if st.button("Ambil Alih", use_container_width=True):
            try:
                open_team(True)
                st.rerun()
            except Exception as err:
                set_feedback(str(err), ok=False)

    lock = st.session_state.get("lock") or {}
    if lock:
        st.caption(f"Lock aktif: {lock.get('lockOwner')}")


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
        .stButton button { min-height: 44px; }
        .stCaption { line-height: 1.35; }
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
