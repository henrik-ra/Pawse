"""Pawse Teams bot — a chat companion inside Microsoft Teams.

Bridges Teams (via Azure Bot Service) to Pawse: it answers questions with the
AI coach (``coach.py``), grounds them in the user's scored day, and offers
**actionable Adaptive Cards** (protect a focus block, reschedule a meeting).

The bot is **optional**: it only activates when ``MicrosoftAppId`` is set (by the
Azure Bot deployment). Until then, the rest of the API runs untouched.

Environment
-----------
MicrosoftAppId / MicrosoftAppPassword / MicrosoftAppType / MicrosoftAppTenantId
    From the Azure Bot resource (see teams/ provisioning steps).
PAWSE_BOT_USER   Pawse user id to read the day for (default: "me").
OUTLOOK_DEEPLINK Base Outlook calendar deeplink for reschedule actions
                 (default: https://outlook.office.com/calendar/).
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from botbuilder.core import (
    ActivityHandler,
    CardFactory,
    ConfigurationBotFrameworkAuthentication,
    CloudAdapter,
    MessageFactory,
    TurnContext,
)
from botbuilder.schema import Activity, ChannelAccount

from . import coach

_BOT_USER = os.environ.get("PAWSE_BOT_USER", "me")
_OUTLOOK_DEEPLINK = os.environ.get(
    "OUTLOOK_DEEPLINK", "https://outlook.office.com/calendar/"
)


class _Config:
    """Adapter configuration read from the standard Bot Framework env vars."""

    APP_ID = os.environ.get("MicrosoftAppId", "")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
    APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
    APP_TENANTID = os.environ.get("MicrosoftAppTenantId", "")


def is_configured() -> bool:
    """True when the Azure Bot credentials are present."""
    return bool(_Config.APP_ID)


def _today() -> str:
    return _dt.date.today().isoformat()


def _get_day(user: str, date: str) -> dict[str, Any] | None:
    """Read the stored scored day; generate a demo day if none exists yet."""
    from . import pawse_store

    day = pawse_store.get_day(user, date)
    if day is not None:
        return day
    try:  # lazy to avoid an import cycle with app.py
        from .app import _demo_day, _score_and_store

        return _score_and_store(_demo_day(user, date), user, date)
    except Exception:
        return None


def _get_history(user: str, days: int = 14) -> list[dict[str, Any]]:
    """Read recent scored days so the coach can answer longitudinal questions."""
    from . import pawse_store

    try:
        return pawse_store.list_recent_days(user, days)
    except Exception:
        return []


def _action_card(day: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build an Adaptive Card with concrete actions when the day looks heavy."""
    if not day:
        return None
    data = day.get("data", day)
    meetings = data.get("meetings", []) or []
    back_to_back = sum(1 for m in meetings if m.get("back_to_back"))
    score = day.get("pawse_score")
    heavy = back_to_back >= 2 or (isinstance(score, (int, float)) and score < 50)
    if not heavy:
        return None

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Dichter Abschnitt erkannt 👀",
                "weight": "Bolder",
                "size": "Medium",
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "text": (
                    f"{back_to_back} Back-to-Back-Calls. Ein geschützter Fokusblock "
                    "oder ein verschobener Termin hält deinen Nachmittag scharf."
                ),
            },
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "🛡️ Fokusblock schützen",
                "data": {"action": "protect_focus"},
            },
            {
                "type": "Action.Submit",
                "title": "🫁 Kurzer Reset",
                "data": {"action": "breathe"},
            },
            {
                "type": "Action.OpenUrl",
                "title": "📅 Termin verschieben",
                "url": _OUTLOOK_DEEPLINK,
            },
        ],
    }


class PawseBot(ActivityHandler):
    """Conversational Pawse companion for Teams."""

    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "Hi, ich bin **Pawse** 🐼 — dein Workday-Energy-Companion. "
                    "Frag mich z. B. *„Wie ist meine Energie heute?“*, "
                    "*„Wie war meine Woche?“* oder *„Wann sollte ich Deep Work machen?“*"
                )

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity

        # 1) Adaptive Card button press → comes back as activity.value (no text).
        value = activity.value if isinstance(activity.value, dict) else None
        if value and value.get("action"):
            await self._handle_action(turn_context, value["action"])
            return

        # 2) Normal chat turn → coach reply grounded in today + longer-term history.
        text = (activity.text or "").strip()
        day = _get_day(_BOT_USER, _today())
        history = _get_history(_BOT_USER)
        reply = coach.coach_reply(text, day, history)
        await turn_context.send_activity(MessageFactory.text(reply))

        card = _action_card(day)
        if card is not None:
            await turn_context.send_activity(
                MessageFactory.attachment(CardFactory.adaptive_card(card))
            )

    async def _handle_action(self, turn_context: TurnContext, action: str) -> None:
        if action == "protect_focus":
            msg = (
                "✅ Vorschlag: Ich blocke dir die nächste freie Lücke als "
                "**Fokuszeit** und setze deinen Teams-Status auf *Focusing*. "
                "(Im Demo-Modus — mit Kalender-Schreibrechten passiert das automatisch.)"
            )
        elif action == "breathe":
            msg = (
                "🫁 Kurzer Reset: 4 Sek. ein – 4 Sek. halten – 6 Sek. aus, 4×. "
                "Danach bist du klarer für den nächsten Termin."
            )
        elif action == "reschedule":
            msg = f"📅 Öffne deinen Kalender zum Verschieben: {_OUTLOOK_DEEPLINK}"
        else:
            msg = "Erledigt. 🐼"
        await turn_context.send_activity(MessageFactory.text(msg))


# --- Singletons used by the /api/messages route -----------------------------

_adapter: CloudAdapter | None = None
_bot: PawseBot | None = None


def get_adapter() -> CloudAdapter:
    global _adapter
    if _adapter is None:
        _adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(_Config))
    return _adapter


def get_bot() -> PawseBot:
    global _bot
    if _bot is None:
        _bot = PawseBot()
    return _bot


async def process(auth_header: str, body: dict[str, Any]):
    """Process one inbound Teams activity. Returns an InvokeResponse or None."""
    activity = Activity().deserialize(body)
    return await get_adapter().process_activity(auth_header, activity, get_bot().on_turn)
