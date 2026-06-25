"""Microsoft Graph calendar service — Smart Meeting Timing.

Provides typed helper functions for:
- Reading calendar events (calendarView)
- Checking attendee availability (findMeetingTimes / getSchedule)
- Rescheduling meetings (PATCH event)
- Creating draft reschedule-request messages (POST /me/messages)

All functions require a valid access token obtained via ms_auth.py.
Health/Pawse data is NEVER included in any outgoing Graph call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from devices.outlook.ms_auth import ensure_access_token, load_tokens, refresh_access_token

# --- Constants ----------------------------------------------------------------

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TIMEOUT = 30

# Retry on transient failures
_session = requests.Session()
_adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504]))
_session.mount("https://", _adapter)


# --- Data structures ----------------------------------------------------------

@dataclass
class MeetingInfo:
    """Meeting metadata needed by the recommendation engine."""
    id: str
    title: str
    start: str  # ISO 8601
    end: str    # ISO 8601
    start_time_local: str  # HH:MM
    end_time_local: str    # HH:MM
    organizer: str
    organizer_email: str
    attendees: list[dict[str, str]]  # [{name, email, response}]
    is_organizer: bool
    is_online: bool
    is_private: bool
    is_recurring: bool
    duration_min: int
    response_statuses: dict[str, str] = field(default_factory=dict)  # email -> status


@dataclass
class TimeSlot:
    """A suggested alternative time slot."""
    start: str  # ISO 8601
    end: str    # ISO 8601
    start_local: str  # HH:MM
    end_local: str    # HH:MM
    confidence: str   # "good" | "fair" | "poor"
    available_count: int
    total_attendees: int


@dataclass
class RescheduleResult:
    """Result of a reschedule operation."""
    success: bool
    message: str
    new_start: str | None = None
    new_end: str | None = None


@dataclass
class DraftMessageResult:
    """Result of creating a draft reschedule-request message."""
    success: bool
    message: str
    draft_id: str | None = None
    subject: str | None = None


# --- Errors -------------------------------------------------------------------

class GraphAuthError(Exception):
    """Raised when authentication fails or tokens are missing."""
    pass


class GraphAPIError(Exception):
    """Raised when a Graph API call fails."""
    def __init__(self, message: str, status_code: int = 0, error_code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class MeetingPermissionError(Exception):
    """Raised when user lacks permission to modify a meeting."""
    pass


# --- Internal helpers ---------------------------------------------------------

def _get_headers() -> dict[str, str]:
    """Get authorization headers, refreshing token if needed."""
    token = ensure_access_token()
    if not token:
        raise GraphAuthError(
            "Not signed in to Microsoft 365. Run: python devices/outlook/ms_auth.py"
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _handle_response(resp: requests.Response) -> dict:
    """Handle Graph API response, raising typed errors."""
    if resp.status_code == 401:
        # Try refresh once
        tokens = load_tokens()
        if tokens and tokens.get("refresh_token"):
            new_tokens = refresh_access_token(tokens["refresh_token"])
            if new_tokens:
                raise GraphAuthError("Token refreshed, please retry the operation.")
        raise GraphAuthError("Session expired. Please re-authenticate: python devices/outlook/ms_auth.py")

    if resp.status_code == 403:
        error = resp.json().get("error", {})
        raise MeetingPermissionError(
            f"Insufficient permissions: {error.get('message', 'Access denied')}. "
            f"Ensure the app has the required delegated permissions."
        )

    if resp.status_code >= 400:
        try:
            error = resp.json().get("error", {})
            msg = error.get("message", resp.text[:200])
            code = error.get("code", "")
        except (json.JSONDecodeError, ValueError):
            msg = resp.text[:200]
            code = ""
        raise GraphAPIError(msg, resp.status_code, code)

    if resp.status_code == 204:
        return {}
    return resp.json()


def _graph_get(path: str, params: dict | None = None) -> dict:
    """GET request to Graph API."""
    resp = _session.get(
        f"{GRAPH_BASE}{path}",
        headers=_get_headers(),
        params=params,
        timeout=_TIMEOUT,
    )
    return _handle_response(resp)


def _graph_post(path: str, body: dict) -> dict:
    """POST request to Graph API."""
    resp = _session.post(
        f"{GRAPH_BASE}{path}",
        headers=_get_headers(),
        json=body,
        timeout=_TIMEOUT,
    )
    return _handle_response(resp)


def _graph_patch(path: str, body: dict) -> dict:
    """PATCH request to Graph API."""
    resp = _session.patch(
        f"{GRAPH_BASE}{path}",
        headers=_get_headers(),
        json=body,
        timeout=_TIMEOUT,
    )
    return _handle_response(resp)


def _parse_local_time(iso: str) -> str:
    """Extract HH:MM from an ISO datetime string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except (ValueError, AttributeError):
        return iso[:5] if len(iso) >= 5 else "00:00"


# --- Public API ---------------------------------------------------------------

def get_calendar_events(date: str) -> list[MeetingInfo]:
    """Fetch all calendar events for a given day.

    Args:
        date: Date string in YYYY-MM-DD format.

    Returns:
        List of MeetingInfo objects with full metadata.
    """
    start_dt = f"{date}T00:00:00"
    end_dt = f"{date}T23:59:59"

    data = _graph_get("/me/calendarView", params={
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "$select": "id,subject,start,end,organizer,attendees,isOnlineMeeting,"
                   "sensitivity,seriesMasterId,type,isCancelled",
        "$orderby": "start/dateTime",
        "$top": 50,
    })

    events = data.get("value", [])
    # Get current user email for is_organizer check
    me = _get_current_user_email()

    meetings = []
    for event in events:
        if event.get("isCancelled"):
            continue

        organizer_data = event.get("organizer", {}).get("emailAddress", {})
        organizer_email = organizer_data.get("address", "").lower()
        organizer_name = organizer_data.get("name", organizer_email)

        attendees_raw = event.get("attendees", [])
        attendees = []
        response_statuses = {}
        for att in attendees_raw:
            email_data = att.get("emailAddress", {})
            email = email_data.get("address", "").lower()
            name = email_data.get("name", email)
            status = att.get("status", {}).get("response", "none")
            attendees.append({"name": name, "email": email, "response": status})
            response_statuses[email] = status

        start_iso = event.get("start", {}).get("dateTime", "")
        end_iso = event.get("end", {}).get("dateTime", "")

        # Duration calculation
        try:
            start_parsed = datetime.fromisoformat(start_iso)
            end_parsed = datetime.fromisoformat(end_iso)
            duration_min = int((end_parsed - start_parsed).total_seconds() / 60)
        except (ValueError, TypeError):
            duration_min = 30

        meetings.append(MeetingInfo(
            id=event.get("id", ""),
            title=event.get("subject", "Meeting"),
            start=start_iso,
            end=end_iso,
            start_time_local=_parse_local_time(start_iso),
            end_time_local=_parse_local_time(end_iso),
            organizer=organizer_name,
            organizer_email=organizer_email,
            attendees=attendees,
            is_organizer=me.lower() == organizer_email,
            is_online=bool(event.get("isOnlineMeeting")),
            is_private=event.get("sensitivity", "normal") == "private",
            is_recurring=event.get("type", "singleInstance") != "singleInstance",
            duration_min=duration_min,
            response_statuses=response_statuses,
        ))

    return meetings


def _get_current_user_email() -> str:
    """Get the signed-in user's email address."""
    data = _graph_get("/me", params={"$select": "mail,userPrincipalName"})
    return data.get("mail") or data.get("userPrincipalName", "")


def find_available_times(
    meeting: MeetingInfo,
    search_start: str,
    search_end: str,
    max_suggestions: int = 3,
) -> list[TimeSlot]:
    """Find alternative meeting times when all/most attendees are free.

    Uses POST /me/findMeetingTimes with attendee constraints.

    Args:
        meeting: The meeting to find alternatives for.
        search_start: ISO datetime for search window start.
        search_end: ISO datetime for search window end.
        max_suggestions: Maximum number of time slots to return.

    Returns:
        List of TimeSlot suggestions ordered by availability.
    """
    # Build attendee list for findMeetingTimes
    attendee_list = []
    for att in meeting.attendees:
        if att["email"]:
            attendee_list.append({
                "emailAddress": {"address": att["email"], "name": att["name"]},
                "type": "required",
            })

    body = {
        "attendees": attendee_list,
        "timeConstraint": {
            "timeslots": [{
                "start": {"dateTime": search_start, "timeZone": "UTC"},
                "end": {"dateTime": search_end, "timeZone": "UTC"},
            }]
        },
        "meetingDuration": f"PT{meeting.duration_min}M",
        "maxCandidates": max_suggestions,
        "isOrganizerOptional": False,
        "returnSuggestionReasons": True,
        "minimumAttendeePercentage": 50.0,
    }

    try:
        data = _graph_post("/me/findMeetingTimes", body)
    except GraphAPIError:
        # Fall back to getSchedule if findMeetingTimes fails
        return _fallback_get_schedule(meeting, search_start, search_end, max_suggestions)

    suggestions = data.get("meetingTimeSuggestions", [])
    total_attendees = len(meeting.attendees)

    slots = []
    for sug in suggestions[:max_suggestions]:
        start_data = sug.get("meetingTimeSlot", {}).get("start", {})
        end_data = sug.get("meetingTimeSlot", {}).get("end", {})
        start_iso = start_data.get("dateTime", "")
        end_iso = end_data.get("dateTime", "")

        confidence_raw = sug.get("confidence", 0)
        if confidence_raw >= 80:
            confidence = "good"
        elif confidence_raw >= 50:
            confidence = "fair"
        else:
            confidence = "poor"

        # Count available attendees
        att_avail = sug.get("attendeeAvailability", [])
        available_count = sum(
            1 for a in att_avail
            if a.get("availability", "") == "free"
        )

        slots.append(TimeSlot(
            start=start_iso,
            end=end_iso,
            start_local=_parse_local_time(start_iso),
            end_local=_parse_local_time(end_iso),
            confidence=confidence,
            available_count=available_count,
            total_attendees=total_attendees,
        ))

    return slots


def _fallback_get_schedule(
    meeting: MeetingInfo,
    search_start: str,
    search_end: str,
    max_suggestions: int,
) -> list[TimeSlot]:
    """Fallback: use getSchedule to find free windows manually."""
    schedules_to_check = [att["email"] for att in meeting.attendees if att["email"]]
    if not schedules_to_check:
        return []

    body = {
        "schedules": schedules_to_check[:20],  # Graph limits to 20
        "startTime": {"dateTime": search_start, "timeZone": "UTC"},
        "endTime": {"dateTime": search_end, "timeZone": "UTC"},
        "availabilityViewInterval": 30,  # 30-minute slots
    }

    try:
        data = _graph_post("/me/calendar/getSchedule", body)
    except GraphAPIError:
        return []

    # Parse availability strings and find common free windows
    schedules = data.get("value", [])
    if not schedules:
        return []

    # Each schedule has an availabilityView string: 0=free, 1=tentative, 2=busy, 3=oof, 4=working-elsewhere
    views = [s.get("availabilityView", "") for s in schedules]
    if not views:
        return []

    min_len = min(len(v) for v in views)
    duration_slots = max(1, meeting.duration_min // 30)
    total_attendees = len(schedules)

    slots = []
    start_parsed = datetime.fromisoformat(search_start.replace("Z", "+00:00"))

    i = 0
    while i <= min_len - duration_slots and len(slots) < max_suggestions:
        # Check if all slots in the window are free for most attendees
        free_count = 0
        for view in views:
            window = view[i:i + duration_slots]
            if all(c in ("0", "1") for c in window):  # free or tentative
                free_count += 1

        if free_count >= len(views) * 0.5:  # at least 50% free
            slot_start = start_parsed + timedelta(minutes=i * 30)
            slot_end = slot_start + timedelta(minutes=meeting.duration_min)
            confidence = "good" if free_count == len(views) else "fair"

            slots.append(TimeSlot(
                start=slot_start.isoformat(),
                end=slot_end.isoformat(),
                start_local=slot_start.strftime("%H:%M"),
                end_local=slot_end.strftime("%H:%M"),
                confidence=confidence,
                available_count=free_count,
                total_attendees=total_attendees,
            ))
            i += duration_slots  # skip past this slot
        else:
            i += 1

    return slots


def reschedule_meeting(
    meeting_id: str,
    new_start: str,
    new_end: str,
    is_organizer: bool,
    user_confirmed: bool,
) -> RescheduleResult:
    """Reschedule a meeting by updating its start/end time.

    Only proceeds if:
    - user_confirmed is True
    - is_organizer is True

    Args:
        meeting_id: Graph event ID.
        new_start: New start time (ISO 8601).
        new_end: New end time (ISO 8601).
        is_organizer: Whether the signed-in user owns this meeting.
        user_confirmed: Whether the user explicitly confirmed.

    Returns:
        RescheduleResult with success status and message.
    """
    if not user_confirmed:
        return RescheduleResult(
            success=False,
            message="Reschedule cancelled — user confirmation is required before moving a meeting.",
        )

    if not is_organizer:
        return RescheduleResult(
            success=False,
            message="You are not the organizer of this meeting. "
                    "Use the draft-reschedule-request option to ask the organizer to move it.",
        )

    body = {
        "start": {"dateTime": new_start, "timeZone": "UTC"},
        "end": {"dateTime": new_end, "timeZone": "UTC"},
    }

    try:
        _graph_patch(f"/me/events/{meeting_id}", body)
    except MeetingPermissionError:
        return RescheduleResult(
            success=False,
            message="Cannot reschedule: you don't have permission to modify this meeting.",
        )
    except GraphAPIError as e:
        if "RecurrenceHasNoOccurrence" in str(e) or "SeriesMaster" in str(e):
            return RescheduleResult(
                success=False,
                message="This is a recurring meeting. Rescheduling individual occurrences "
                        "of recurring meetings requires additional handling. "
                        "Consider asking the organizer to update the series.",
            )
        return RescheduleResult(
            success=False,
            message=f"Failed to reschedule: {e}",
        )

    return RescheduleResult(
        success=True,
        message="Meeting rescheduled successfully. Attendees will receive an update.",
        new_start=new_start,
        new_end=new_end,
    )


def create_reschedule_request_draft(
    meeting: MeetingInfo,
    suggested_start: str,
    suggested_end: str,
    reason: str | None = None,
) -> DraftMessageResult:
    """Create a draft email asking the organizer to reschedule.

    Used when the signed-in user is NOT the organizer.
    The reason uses professional language — no health/stress data is included.

    Args:
        meeting: The meeting to request rescheduling for.
        suggested_start: Suggested new start time (ISO).
        suggested_end: Suggested new end time (ISO).
        reason: Optional professional reason for the request.

    Returns:
        DraftMessageResult with the draft message ID.
    """
    if not reason:
        reason = "This meeting may be more effective in a different time slot."

    suggested_time_str = _parse_local_time(suggested_start)
    suggested_end_str = _parse_local_time(suggested_end)

    subject = f"Request to reschedule: {meeting.title}"
    body_text = (
        f"Hi {meeting.organizer},\n\n"
        f"Would it be possible to move \"{meeting.title}\" "
        f"(currently {meeting.start_time_local}–{meeting.end_time_local}) "
        f"to {suggested_time_str}–{suggested_end_str}?\n\n"
        f"Reason: {reason}\n\n"
        f"I checked availability and this time works for the attendees. "
        f"Let me know if that works for you.\n\n"
        f"Thanks!"
    )

    message_body = {
        "subject": subject,
        "body": {
            "contentType": "text",
            "content": body_text,
        },
        "toRecipients": [{
            "emailAddress": {
                "address": meeting.organizer_email,
                "name": meeting.organizer,
            }
        }],
        "isDraft": True,
    }

    try:
        data = _graph_post("/me/messages", message_body)
    except GraphAPIError as e:
        return DraftMessageResult(
            success=False,
            message=f"Failed to create draft message: {e}",
        )

    return DraftMessageResult(
        success=True,
        message="Draft reschedule request created in your Outlook drafts folder.",
        draft_id=data.get("id"),
        subject=subject,
    )


def get_reschedule_request_text(
    meeting: MeetingInfo,
    suggested_start: str,
    suggested_end: str,
    reason: str | None = None,
) -> str:
    """Return suggested text for a reschedule request (without creating a draft).

    Useful when Mail.ReadWrite permission is not available.
    """
    if not reason:
        reason = "This meeting may be more effective in a different time slot."

    suggested_time_str = _parse_local_time(suggested_start)
    suggested_end_str = _parse_local_time(suggested_end)

    return (
        f"Subject: Request to reschedule: {meeting.title}\n\n"
        f"Hi {meeting.organizer},\n\n"
        f"Would it be possible to move \"{meeting.title}\" "
        f"(currently {meeting.start_time_local}–{meeting.end_time_local}) "
        f"to {suggested_time_str}–{suggested_end_str}?\n\n"
        f"Reason: {reason}\n\n"
        f"I checked availability and this time works for the attendees. "
        f"Let me know if that works for you.\n\n"
        f"Thanks!"
    )
