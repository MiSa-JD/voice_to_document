from __future__ import annotations

from app.renderer import format_timestamp
from app.schema import ActionItem, CategorySummary, Evidence, SummaryFact


def render_summary_markdown(summary: CategorySummary, category: str) -> bytes:
    lines = ["# 요약", "", f"- 범주: {category}", ""]
    sections: list[tuple[str, object]]
    if summary.template == "lecture":
        sections = [
            ("핵심 주제", summary.core_topics),
            ("개념", summary.concepts),
            ("예시", summary.examples),
            ("복습 항목", summary.review_items),
        ]
    elif summary.template == "meeting":
        sections = [
            ("목적", [summary.purpose]),
            ("논의 내용", summary.discussion),
            ("결정 사항", summary.decisions),
            ("할 일", summary.action_items),
            ("미해결 사항", summary.open_questions),
        ]
    elif summary.template == "daily_conversation":
        sections = [
            ("주요 화제", summary.main_topics),
            ("합의·약속", summary.agreements),
            ("기억할 사항", summary.reminders),
        ]
    elif summary.template == "game_list":
        sections = [
            ("게임", summary.games),
            ("선호·평가", summary.preferences),
            ("후속 확인", summary.follow_ups),
        ]
    else:
        sections = [
            ("핵심 요약", [summary.key_summary]),
            ("주요 사실", summary.key_facts),
            ("후속 항목", summary.follow_ups),
        ]
    for title, items in sections:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["- 없음", ""])
            continue
        for item in _summary_items(items):
            if isinstance(item, SummaryFact):
                lines.append(f"- {item.text}{_evidence_suffix(item.evidence)}")
            else:
                assignee = item.assignee or "확인되지 않음"
                due_date = item.due_date or "확인되지 않음"
                lines.append(
                    f"- {item.task} (담당자: {assignee}, 기한: {due_date})"
                    f"{_evidence_suffix(item.evidence)}"
                )
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode()


def _summary_items(value: object) -> list[SummaryFact | ActionItem]:
    if not isinstance(value, list) or not all(
        isinstance(item, (SummaryFact, ActionItem)) for item in value
    ):
        raise TypeError("summary section must contain facts or action items")
    return value


def _evidence_suffix(evidence: list[Evidence]) -> str:
    values = ", ".join(
        f"{item.segment_id} {format_timestamp(item.start_ms)}–{format_timestamp(item.end_ms)}"
        for item in evidence
    )
    return f" — 근거: {values}"
