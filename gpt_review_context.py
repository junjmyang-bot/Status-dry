"""Build a GPT-ready review packet for the Dry Status UI.

Usage:
    python gpt_review_context.py
    python gpt_review_context.py > review_packet.txt

The output is intended for UX / workflow review, not for code generation.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parent

FILES = {
    "readme": ROOT / "README.md",
    "sample_report": ROOT / "report.sample.json",
    "ui": ROOT / "public" / "index.html",
    "telegram_formatter": ROOT / "src" / "formatters" / "telegramFormatter.js",
    "sheets_formatter": ROOT / "src" / "formatters" / "sheetsRowFormatter.js",
}

PROJECT_CONTEXT = {
    "app_name": "Dry Status Board",
    "domain": "Factory dry-slot operations",
    "primary_users": [
        "shop-floor operators",
        "team leaders",
        "handover / shift-change operators",
    ],
    "main_goal": (
        "Reduce Telegram-style free-text reporting and make slot updates visible, "
        "structured, and harder to miss."
    ),
    "current_main_groups": [
        "SEDANG DRY",
        "KOSONG",
        "TIDAK DIPAKAI",
        "BUTUH TINDAKAN",
    ],
    "butuh_tindakan_meaning": [
        "Defrost has finished and dry should start soon",
        "Dry is due / finished and the slot should be checked or unloaded",
    ],
}

RECENT_DESIGN_DECISIONS = [
    "Use only a few strong machine-state groups instead of many colors.",
    "Show currently drying slots in a separate time-ordered list.",
    "Treat partial-out as a separate concept from dry ulang.",
    "Hide defrost fields when a product does not require defrost.",
    "Keep local draft state in browser storage.",
]

OPEN_REVIEW_QUESTIONS = [
    "Are the current main groups understandable for low-context operators?",
    "Should BUTUH TINDAKAN be split into explicit actions such as MULAI DRY and KELUARKAN?",
    "Is the Kondisi Slot dropdown too risky compared to button-based forward actions?",
    "How should partial-out / some quantity finished while the rest still dries be shown?",
    "What should be part of urgent hourly attention vs end-of-shift handover checks?",
]

REVIEW_INSTRUCTIONS = """
You are reviewing a real shop-floor UI, not making a generic design critique.

Focus on:
- operator confusion
- missed actions
- ambiguous labels
- action priority
- workflow safety
- partial / exception handling

Do not focus on visual polish unless it directly causes operational mistakes.
Do not praise the UI. Only identify weak points and propose simpler alternatives.

Answer format:
1. Top 5 UX / workflow risks
2. Why each risk matters in real operation
3. A simpler redesign direction for each
4. A proposed final information structure with:
   - main status groups
   - action labels
   - what belongs in slot cards
   - what belongs in handover / end-of-shift checks
"""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> str:
    data = json.loads(read_text(path))
    return json.dumps(data, indent=2, ensure_ascii=False)


def excerpt(text: str, max_chars: int = 5000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[truncated]"


def section(title: str, body: str) -> str:
    return f"{title}\n{'=' * len(title)}\n{body.strip()}\n"


def build_context_block() -> str:
    lines = [
        f"- App: {PROJECT_CONTEXT['app_name']}",
        f"- Domain: {PROJECT_CONTEXT['domain']}",
        "- Primary users: " + ", ".join(PROJECT_CONTEXT["primary_users"]),
        f"- Goal: {PROJECT_CONTEXT['main_goal']}",
        "- Current main groups: " + ", ".join(PROJECT_CONTEXT["current_main_groups"]),
        "- BUTUH TINDAKAN currently means:",
    ]
    lines.extend(f"  - {item}" for item in PROJECT_CONTEXT["butuh_tindakan_meaning"])
    lines.append("- Recent design decisions:")
    lines.extend(f"  - {item}" for item in RECENT_DESIGN_DECISIONS)
    lines.append("- Open review questions:")
    lines.extend(f"  - {item}" for item in OPEN_REVIEW_QUESTIONS)
    return "\n".join(lines)


def build_packet() -> str:
    readme = excerpt(read_text(FILES["readme"]), 2500)
    sample_report = read_json(FILES["sample_report"])
    ui_excerpt = excerpt(read_text(FILES["ui"]), 9000)
    telegram_excerpt = excerpt(read_text(FILES["telegram_formatter"]), 2500)
    sheets_excerpt = excerpt(read_text(FILES["sheets_formatter"]), 2500)

    return "\n\n".join(
        [
            section("Review Prompt", textwrap.dedent(REVIEW_INSTRUCTIONS)),
            section("Project Context", build_context_block()),
            section("README Excerpt", readme),
            section("Sample Report JSON", sample_report),
            section("UI File Excerpt", ui_excerpt),
            section("Telegram Formatter Excerpt", telegram_excerpt),
            section("Sheets Formatter Excerpt", sheets_excerpt),
        ]
    )


if __name__ == "__main__":
    print(build_packet())
