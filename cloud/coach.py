"""Pawse AI coach — turns a scored day + a user question into a short, supportive,
output-oriented coaching reply.

Design
------
* Uses **Azure OpenAI** (keyless, via managed identity) when configured.
* Falls back to a **deterministic, rule-based** reply when Azure OpenAI is not
  configured or unreachable — so the Teams bot *always* answers, even before
  the model is provisioned.

Positioning is baked into the system prompt: Pawse is a **performance** companion,
never a medical/diagnostic tool. It frames recovery as a way to perform better
and never labels stress, burnout or emotions.

Environment
-----------
AZURE_OPENAI_ENDPOINT      e.g. https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT    deployment name (default: gpt-4o-mini)
AZURE_OPENAI_API_VERSION   default: 2024-10-21
AZURE_CLIENT_ID            user-assigned managed identity (same one Cosmos uses)
"""
from __future__ import annotations

import os
from typing import Any

_AOAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
_AOAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
_AOAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

_SYSTEM_PROMPT = (
    "You are Pawse, a friendly workday-energy companion. You help people protect "
    "their energy and focus so they can perform sustainably. You are a PERFORMANCE "
    "coach — NOT a wellness app and NOT a medical or diagnostic tool. Never "
    "diagnose stress, burnout or emotions, and never label how someone feels. "
    "Frame recovery as a way to perform better, and be bidirectional: when energy "
    "is high, encourage focused deep work; when the day is heavy, suggest a small "
    "reset. You have access to the user's data: today's scored day AND their "
    "longer-term history (score trends, meeting-load patterns, voice-signal trends "
    "over days and weeks). You can answer analytical questions about this data — "
    "describe patterns, averages and changes factually and cite concrete numbers "
    "and dates from the context — but still never diagnose. Ground advice in the "
    "real workday context and prefer ONE concrete, output-oriented next action. Be "
    "concise (2-5 sentences); for data questions a short bulleted summary is fine. "
    "Reply in the user's language."
)

_client = None


def is_enabled() -> bool:
    """True when an Azure OpenAI endpoint is configured."""
    return bool(_AOAI_ENDPOINT)


def _get_client():
    """Lazily build the keyless AzureOpenAI client (cached). None if unconfigured."""
    global _client
    if _client is not None or not _AOAI_ENDPOINT:
        return _client

    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID")
        ),
        "https://cognitiveservices.azure.com/.default",
    )
    _client = AzureOpenAI(
        azure_endpoint=_AOAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version=_AOAI_API_VERSION,
    )
    return _client


def _day_summary(day: dict[str, Any]) -> str:
    """Compact, model-friendly summary of a scored day for grounding."""
    if not day:
        return "No data yet for today."

    data = day.get("data", day)
    meetings = data.get("meetings", []) or []
    back_to_back = sum(1 for m in meetings if m.get("back_to_back"))
    after_hours = sum(1 for m in meetings if m.get("after_hours"))
    wearable = data.get("wearable", {}) or {}
    breaks = data.get("breaks", {}) or {}

    lines = [
        f"Pawse score: {day.get('pawse_score', 'n/a')} ({day.get('label', 'n/a')})",
        f"Meetings today: {len(meetings)} "
        f"(back-to-back: {back_to_back}, after-hours: {after_hours})",
        f"Lunch break protected: {breaks.get('lunch_break', 'unknown')}",
        f"Longest free gap (min): {breaks.get('longest_gap_minutes', 'n/a')}",
        f"Steps: {wearable.get('steps', 'n/a')}, "
        f"resting HR: {wearable.get('resting_hr', 'n/a')}",
    ]
    recs = day.get("recommendations") or []
    if recs:
        lines.append("Current recommendations: " + "; ".join(str(r) for r in recs[:3]))
    return "\n".join(lines)


def _history_summary(history: list[dict[str, Any]] | None) -> str:
    """Compact longitudinal summary (score/meeting/voice trends) for grounding."""
    if not history:
        return ""

    rows = []          # (date, score, meeting_count, voice_stress)
    scores: list[float] = []
    voice: list[float] = []
    loads: list[int] = []
    for h in history:
        if not isinstance(h, dict):
            continue
        data = h.get("data", h)
        score = h.get("pawse_score")
        date = h.get("date") or data.get("date") or "?"
        meetings = data.get("meetings", []) or []
        v = data.get("voice") or {}
        vs = v.get("avg_stress_index")
        if vs is None:
            vs = v.get("stressIndex")
        rows.append((date, score, len(meetings), vs))
        if isinstance(score, (int, float)):
            scores.append(float(score))
        if isinstance(vs, (int, float)):
            voice.append(float(vs))
        loads.append(len(meetings))

    lines = [
        "Recent days (newest first): "
        + ", ".join(f"{d}={s}" for d, s, _, _ in rows[:14])
    ]
    if scores:
        lines.append(
            f"Score avg {round(sum(scores) / len(scores), 1)}, "
            f"min {min(scores):.0f}, max {max(scores):.0f}, over {len(scores)} days"
        )
        chrono = list(reversed(scores))      # oldest → newest
        if len(chrono) >= 4:
            half = len(chrono) // 2
            early = sum(chrono[:half]) / half
            late = sum(chrono[half:]) / (len(chrono) - half)
            delta = round(late - early, 1)
            direction = (
                "improving" if delta > 2 else "declining" if delta < -2 else "stable"
            )
            lines.append(
                f"Score trend: {direction} ({'+' if delta >= 0 else ''}{delta})"
            )
    valid = [r for r in rows if isinstance(r[1], (int, float))]
    if valid:
        worst = min(valid, key=lambda r: r[1])
        lines.append(
            f"Worst recent day: {worst[0]} (score {worst[1]}, {worst[2]} meetings)"
        )
    if voice:
        lines.append(
            f"Voice stress index: avg {round(sum(voice) / len(voice), 2)} "
            f"(range {min(voice):.2f}-{max(voice):.2f}, {len(voice)} recordings)"
        )
    if loads:
        lines.append(f"Meeting load: avg {round(sum(loads) / len(loads), 1)}/day")
    return "\n".join(lines)


def _looks_analytical(question: str) -> bool:
    q = (question or "").lower()
    keys = (
        "woche", "trend", "verlauf", "letzte", "history", "historie", "vergleich",
        "monat", "tage", "durchschnitt", "average", "week", "compare", "pattern",
        "muster", "entwicklung",
    )
    return any(k in q for k in keys)


def _fallback_reply(
    question: str, day: dict[str, Any], history: list[dict[str, Any]] | None = None
) -> str:
    """Deterministic reply used when Azure OpenAI isn't available."""
    # Analytical / longitudinal question → summarise the trend factually.
    if history and _looks_analytical(question):
        scores = [
            float(h.get("pawse_score"))
            for h in history
            if isinstance(h, dict) and isinstance(h.get("pawse_score"), (int, float))
        ]
        if scores:
            avg = round(sum(scores) / len(scores), 1)
            chrono = list(reversed(scores))
            half = max(1, len(chrono) // 2)
            delta = round(
                sum(chrono[half:]) / max(1, len(chrono) - half)
                - sum(chrono[:half]) / half,
                1,
            )
            direction = (
                "geht aufwärts" if delta > 2
                else "geht runter" if delta < -2
                else "ist stabil"
            )
            return (
                f"Über die letzten {len(scores)} Tage liegt dein Pawse-Score im "
                f"Schnitt bei {avg} (von {min(scores):.0f} bis {max(scores):.0f}) und "
                f"{direction}. Sag „Details“, wenn ich den schlechtesten Tag und "
                "seine Ursachen aufschlüsseln soll. 🐼"
            )

    if not day:
        return (
            "Ich habe für heute noch keine Energiedaten. Sobald dein Tag erfasst "
            "ist, sage ich dir, wann du Vollgas geben und wann du kurz resetten "
            "solltest. 🐼"
        )

    score = day.get("pawse_score")
    label = (day.get("label") or "").lower()
    data = day.get("data", day)
    meetings = data.get("meetings", []) or []
    back_to_back = sum(1 for m in meetings if m.get("back_to_back"))
    recs = day.get("recommendations") or []
    tip = str(recs[0]) if recs else None

    head = f"Dein Pawse-Score ist {score}" if score is not None else "Dein Tag"
    if "low" in label or (isinstance(score, (int, float)) and score < 45):
        body = (
            f"{head} — ein dichter Tag"
            + (f" mit {back_to_back} Back-to-Back-Calls" if back_to_back else "")
            + ". Ein 2-Minuten-Reset jetzt hält dich für den nächsten wichtigen "
            "Termin scharf."
        )
    elif isinstance(score, (int, float)) and score >= 70:
        body = (
            f"{head} — starke Energie. Das ist dein Fenster für eine harte "
            "Deep-Work-Aufgabe; schütz dir jetzt einen Fokusblock."
        )
    else:
        body = (
            f"{head} — solide. Achte darauf, deine Pause zu schützen, damit der "
            "Nachmittag stabil bleibt."
        )
    if tip:
        body += f" Tipp: {tip}"
    return body


def coach_reply(
    question: str,
    day: dict[str, Any] | None,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Return a coaching reply grounded in today's ``day`` and longer-term ``history``."""
    day = day or {}
    client = _get_client()
    if client is None:
        return _fallback_reply(question, day, history)

    try:
        context = _day_summary(day)
        trend = _history_summary(history)
        if trend:
            context += "\n\nLonger-term history:\n" + trend
        resp = client.chat.completions.create(
            model=_AOAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"My data:\n{context}\n\nQuestion: {question or 'How am I doing today?'}",
                },
            ],
            max_tokens=320,
            temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip() or _fallback_reply(
            question, day, history
        )
    except Exception:
        # Model unreachable / quota / auth — degrade gracefully, never crash the bot.
        return _fallback_reply(question, day, history)
