from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ASSET_DIR = BASE_DIR / "assets"

REQUIRED_COLUMNS = {
    "calendar": {
        "date",
        "meeting_id",
        "title",
        "start_time",
        "end_time",
        "meeting_type",
        "organizer",
        "is_required",
        "is_after_hours",
    },
    "teams": {
        "date",
        "meeting_id",
        "total_minutes",
        "speaking_minutes",
        "chat_messages",
        "action_items",
        "interruptions",
        "sentiment_score",
        "stress_keywords",
    },
    "wearable": {
        "date",
        "time",
        "heart_rate",
        "baseline_heart_rate",
        "steps",
        "hrv_ms",
        "stress_level",
        "sleep_hours",
    },
    "checkins": {"date", "time", "energy_level", "mood", "notes"},
}


st.set_page_config(
    page_title="Pawse",
    page_icon="🐼",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

        :root {
            --pawse-bg: #090014;
            --pawse-panel: rgba(35, 10, 68, 0.78);
            --pawse-panel-strong: rgba(58, 18, 102, 0.88);
            --pawse-purple: #b56cff;
            --pawse-pink: #ff8cff;
            --pawse-blue: #62d9ff;
            --pawse-text: #f8edff;
            --pawse-muted: #cbb2ea;
            --pawse-good: #4ee6a8;
            --pawse-warn: #ffd166;
            --pawse-risk: #ff6b9a;
        }

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }

        .stApp {
            color: var(--pawse-text);
            background:
                radial-gradient(circle at 16% 18%, rgba(181,108,255,0.38), transparent 28%),
                radial-gradient(circle at 82% 12%, rgba(98,217,255,0.16), transparent 24%),
                radial-gradient(circle at 64% 78%, rgba(255,140,255,0.20), transparent 24%),
                linear-gradient(135deg, #05000d 0%, #16002b 48%, #090014 100%);
        }

        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            opacity: 0.36;
            background-image:
                radial-gradient(#ffffff 0.7px, transparent 0.7px),
                radial-gradient(#c77dff 0.9px, transparent 0.9px);
            background-position: 0 0, 34px 48px;
            background-size: 72px 72px, 96px 96px;
            z-index: 0;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(15,0,32,0.98), rgba(43,10,78,0.96));
            border-right: 1px solid rgba(181,108,255,0.24);
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .block-container {
            padding-top: 1.4rem;
            position: relative;
            z-index: 1;
        }

        .pawse-hero {
            border: 1px solid rgba(181,108,255,0.38);
            border-radius: 30px;
            padding: 28px 32px;
            margin-bottom: 20px;
            background:
                linear-gradient(135deg, rgba(71,18,128,0.78), rgba(18,3,45,0.86)),
                radial-gradient(circle at top right, rgba(255,140,255,0.28), transparent 34%);
            box-shadow: 0 0 42px rgba(181,108,255,0.22), inset 0 0 24px rgba(255,255,255,0.04);
        }

        .pawse-kicker {
            color: var(--pawse-blue);
            font-size: 0.82rem;
            font-weight: 800;
            letter-spacing: 0.16rem;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .pawse-title {
            font-size: 3.2rem;
            font-weight: 800;
            margin: 0;
            line-height: 1;
            text-shadow: 0 0 28px rgba(181,108,255,0.92);
        }

        .pawse-subtitle {
            color: var(--pawse-muted);
            font-size: 1.05rem;
            margin-top: 12px;
            max-width: 780px;
        }

        .pawse-card {
            border: 1px solid rgba(181,108,255,0.30);
            border-radius: 24px;
            padding: 22px;
            background: var(--pawse-panel);
            box-shadow: 0 0 30px rgba(80, 24, 144, 0.24), inset 0 0 20px rgba(255,255,255,0.03);
            min-height: 138px;
        }

        .pawse-label {
            color: var(--pawse-muted);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08rem;
        }

        .pawse-value {
            font-size: 2.2rem;
            font-weight: 800;
            margin-top: 6px;
            color: var(--pawse-text);
        }

        .pawse-caption {
            color: var(--pawse-muted);
            margin-top: 8px;
            font-size: 0.92rem;
        }

        .pawse-pill {
            display: inline-block;
            border-radius: 999px;
            padding: 7px 12px;
            margin: 4px 6px 4px 0;
            color: var(--pawse-text);
            background: rgba(181,108,255,0.18);
            border: 1px solid rgba(181,108,255,0.36);
            font-weight: 700;
        }

        .recommendation {
            border-left: 4px solid var(--pawse-purple);
            padding: 12px 16px;
            margin-bottom: 12px;
            border-radius: 14px;
            background: rgba(255,255,255,0.055);
        }

        .privacy-note {
            border: 1px solid rgba(98,217,255,0.36);
            background: rgba(98,217,255,0.08);
            border-radius: 20px;
            padding: 18px;
            color: #dbf7ff;
        }

        div[data-testid="stMetricValue"] {
            color: var(--pawse-text);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(181,108,255,0.28);
            border-radius: 18px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data
def load_csv(relative_path: str, data_key: str) -> pd.DataFrame:
    path = DATA_DIR / relative_path
    if not path.exists():
        st.error(f"Missing data file: {path}")
        st.stop()

    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS[data_key] - set(frame.columns)
    if missing:
        st.error(
            f"{relative_path} is missing columns: {', '.join(sorted(missing))}. "
            "Keep the schema from data/data_schema.md when replacing sample data."
        )
        st.stop()

    return frame


def load_data() -> dict[str, pd.DataFrame]:
    calendar = load_csv("calendar/meetings.csv", "calendar")
    teams = load_csv("teams/meeting_metadata.csv", "teams")
    wearable = load_csv("wearable/wearable_signals.csv", "wearable")
    checkins = load_csv("checkins/mood_checkins.csv", "checkins")

    for frame in (calendar, teams, wearable, checkins):
        frame["date"] = pd.to_datetime(frame["date"]).dt.date

    calendar["start_dt"] = pd.to_datetime(
        calendar["date"].astype(str) + " " + calendar["start_time"]
    )
    calendar["end_dt"] = pd.to_datetime(
        calendar["date"].astype(str) + " " + calendar["end_time"]
    )
    calendar["duration_minutes"] = (
        calendar["end_dt"] - calendar["start_dt"]
    ).dt.total_seconds() / 60
    wearable["timestamp"] = pd.to_datetime(
        wearable["date"].astype(str) + " " + wearable["time"]
    )

    return {
        "calendar": calendar,
        "teams": teams,
        "wearable": wearable,
        "checkins": checkins,
    }


def count_back_to_back(meetings: pd.DataFrame) -> int:
    work_meetings = meetings[meetings["meeting_type"].str.lower() != "focus"].sort_values(
        "start_dt"
    )
    if work_meetings.empty:
        return 0

    previous_end = None
    count = 0
    for _, row in work_meetings.iterrows():
        if previous_end is not None and row["start_dt"] <= previous_end:
            count += 1
        previous_end = max(previous_end, row["end_dt"]) if previous_end else row["end_dt"]
    return count


def longest_meeting_streak(meetings: pd.DataFrame) -> float:
    work_meetings = meetings[meetings["meeting_type"].str.lower() != "focus"].sort_values(
        "start_dt"
    )
    if work_meetings.empty:
        return 0.0

    streak_start = work_meetings.iloc[0]["start_dt"]
    streak_end = work_meetings.iloc[0]["end_dt"]
    longest = streak_end - streak_start

    for _, row in work_meetings.iloc[1:].iterrows():
        gap_minutes = (row["start_dt"] - streak_end).total_seconds() / 60
        if gap_minutes <= 5:
            streak_end = max(streak_end, row["end_dt"])
        else:
            longest = max(longest, streak_end - streak_start)
            streak_start = row["start_dt"]
            streak_end = row["end_dt"]

    longest = max(longest, streak_end - streak_start)
    return round(longest.total_seconds() / 3600, 1)


def calculate_pawse_score(
    meetings: pd.DataFrame, teams: pd.DataFrame, wearable: pd.DataFrame, checkins: pd.DataFrame
) -> tuple[int, list[str]]:
    work_meetings = meetings[meetings["meeting_type"].str.lower() != "focus"]
    meeting_hours = work_meetings["duration_minutes"].sum() / 60
    focus_hours = meetings.loc[
        meetings["meeting_type"].str.lower() == "focus", "duration_minutes"
    ].sum() / 60
    back_to_back = count_back_to_back(meetings)
    after_hours = int(work_meetings["is_after_hours"].astype(str).str.lower().eq("true").sum())
    avg_speaking_share = (
        teams["speaking_minutes"].sum() / teams["total_minutes"].sum()
        if teams["total_minutes"].sum()
        else 0
    )
    avg_stress = wearable["stress_level"].mean() if not wearable.empty else 0
    latest_steps = wearable["steps"].max() if not wearable.empty else 0
    elevated_hr_points = int(
        (wearable["heart_rate"] >= wearable["baseline_heart_rate"] + 20).sum()
    )
    avg_energy = checkins["energy_level"].mean() if not checkins.empty else 75

    score = 18
    score += min(meeting_hours * 8, 34)
    score += min(back_to_back * 8, 20)
    score += min(after_hours * 8, 12)
    score += 10 if focus_hours < 1 else 0
    score += 10 if latest_steps < 2500 else 0
    score += min(elevated_hr_points * 4, 14)
    score += 8 if avg_speaking_share > 0.55 else 0
    score += max((avg_stress - 45) * 0.35, 0)
    score += max((55 - avg_energy) * 0.25, 0)
    score = int(round(max(0, min(score, 100))))

    reasons: list[str] = []
    if meeting_hours >= 4.5:
        reasons.append(f"{meeting_hours:.1f} hours in meetings")
    if back_to_back:
        reasons.append(f"{back_to_back} back-to-back meeting handoffs")
    if focus_hours < 1:
        reasons.append("less than 1 hour of protected focus time")
    if latest_steps < 2500:
        reasons.append(f"low movement signal ({int(latest_steps):,} steps)")
    if elevated_hr_points:
        reasons.append(f"{elevated_hr_points} elevated heart-rate readings")
    if avg_speaking_share > 0.55:
        reasons.append(f"high speaking load ({avg_speaking_share:.0%})")
    if after_hours:
        reasons.append(f"{after_hours} after-hours meeting")

    return score, reasons[:5]


def status_for_score(score: int) -> tuple[str, str, str]:
    if score >= 75:
        return "High strain", "#ff6b9a", "Pawse recommends recovery before more deep work."
    if score >= 50:
        return "Moderate strain", "#ffd166", "Pawse sees some load, but it is manageable."
    return "Balanced", "#4ee6a8", "Pawse sees a healthy rhythm today."


def render_metric_card(label: str, value: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="pawse-card">
            <div class="pawse-label">{label}</div>
            <div class="pawse-value">{value}</div>
            <div class="pawse-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def recommendation_list(score: int, reasons: list[str]) -> list[str]:
    recommendations = []
    if score >= 75:
        recommendations.append("Block a 30-minute recovery Pawse before the next work block.")
    if any("back-to-back" in reason for reason in reasons):
        recommendations.append("Add a 10-minute buffer between the next two meetings.")
    if any("focus" in reason for reason in reasons):
        recommendations.append("Protect one focus block tomorrow before accepting new meetings.")
    if any("movement" in reason for reason in reasons):
        recommendations.append("Turn one 1:1 into a walking meeting or stretch break.")
    if any("speaking" in reason for reason in reasons):
        recommendations.append("Rebalance the next meeting by assigning a co-facilitator.")
    if not recommendations:
        recommendations.append("Keep the current rhythm and preserve your recovery gaps.")
    return recommendations[:4]


def main() -> None:
    inject_theme()
    data = load_data()
    mascot_path = ASSET_DIR / "pawse_mascot.png"

    with st.sidebar:
        if mascot_path.exists():
            st.image(str(mascot_path), use_column_width=True)
        st.markdown("## Pawse")
        st.caption("Private wellbeing signals for healthier workdays.")

        dates = sorted(data["calendar"]["date"].unique())
        selected_date = st.selectbox("Dashboard date", dates, index=len(dates) - 2 if len(dates) > 1 else 0)
        st.markdown("---")
        st.markdown("### Connected data files")
        st.caption("Replace these CSVs with actual exports later.")
        st.code(
            "data/calendar/meetings.csv\n"
            "data/teams/meeting_metadata.csv\n"
            "data/wearable/wearable_signals.csv\n"
            "data/checkins/mood_checkins.csv",
            language="text",
        )

    meetings = data["calendar"][data["calendar"]["date"] == selected_date].copy()
    teams = data["teams"][data["teams"]["date"] == selected_date].copy()
    wearable = data["wearable"][data["wearable"]["date"] == selected_date].copy()
    checkins = data["checkins"][data["checkins"]["date"] == selected_date].copy()

    score, reasons = calculate_pawse_score(meetings, teams, wearable, checkins)
    status, status_color, status_caption = status_for_score(score)

    st.markdown(
        f"""
        <div class="pawse-hero">
            <div class="pawse-kicker">Private opt-in wellbeing assistant</div>
            <h1 class="pawse-title">Pawse Dashboard</h1>
            <div class="pawse-subtitle">
                A panda-themed command center for meeting strain, device signals, mood check-ins,
                and gentle recovery suggestions. No diagnosis. No manager dashboard. Just personal support.
            </div>
            <div style="margin-top:18px;">
                <span class="pawse-pill">🐼 Panda mode</span>
                <span class="pawse-pill">✨ Galaxy theme</span>
                <span class="pawse-pill">🔒 User-only insights</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    score_col, status_col, meeting_col, recovery_col = st.columns([1.3, 1, 1, 1])
    work_meetings = meetings[meetings["meeting_type"].str.lower() != "focus"]
    focus_minutes = meetings.loc[
        meetings["meeting_type"].str.lower() == "focus", "duration_minutes"
    ].sum()
    meeting_hours = work_meetings["duration_minutes"].sum() / 60
    latest_steps = int(wearable["steps"].max()) if not wearable.empty else 0

    with score_col:
        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=score,
                number={"suffix": "/100", "font": {"size": 44, "color": "#f8edff"}},
                title={"text": "Pawse Score", "font": {"size": 18, "color": "#cbb2ea"}},
                gauge={
                    "axis": {"range": [0, 100], "tickcolor": "#cbb2ea"},
                    "bar": {"color": status_color},
                    "bgcolor": "rgba(255,255,255,0.08)",
                    "borderwidth": 0,
                    "steps": [
                        {"range": [0, 50], "color": "rgba(78,230,168,0.28)"},
                        {"range": [50, 75], "color": "rgba(255,209,102,0.28)"},
                        {"range": [75, 100], "color": "rgba(255,107,154,0.28)"},
                    ],
                },
            )
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=275,
            margin=dict(l=20, r=20, t=35, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with status_col:
        render_metric_card("Panda status", status, status_caption)
    with meeting_col:
        render_metric_card("Meeting load", f"{meeting_hours:.1f}h", f"{len(work_meetings)} meetings today")
    with recovery_col:
        render_metric_card("Movement", f"{latest_steps:,}", "steps captured in wearable file")

    if reasons:
        st.markdown("### Why Pawse flagged today")
        st.markdown(
            "".join(f'<span class="pawse-pill">{reason}</span>' for reason in reasons),
            unsafe_allow_html=True,
        )

    left, right = st.columns([1.1, 0.9])
    with left:
        st.markdown("### Workday timeline")
        timeline = meetings.assign(
            block=meetings["meeting_type"].where(
                meetings["meeting_type"].str.lower() == "focus", "Meeting"
            )
        )
        fig = px.timeline(
            timeline,
            x_start="start_dt",
            x_end="end_dt",
            y="block",
            color="meeting_type",
            hover_data=["title", "organizer", "duration_minutes"],
            color_discrete_sequence=["#b56cff", "#62d9ff", "#ff8cff", "#ffd166"],
        )
        fig.update_yaxes(autorange="reversed", title="")
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.04)",
            font_color="#f8edff",
            height=330,
            margin=dict(l=10, r=10, t=20, b=20),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("### Recovery suggestions")
        for item in recommendation_list(score, reasons):
            st.markdown(f'<div class="recommendation">{item}</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="privacy-note">
                <strong>Privacy promise:</strong> Pawse is opt-in and personal.
                It does not diagnose burnout, depression, or health conditions,
                and it does not create a manager-facing dashboard.
            </div>
            """,
            unsafe_allow_html=True,
        )

    signal_col, team_col = st.columns(2)
    with signal_col:
        st.markdown("### Device and wearable signals")
        if wearable.empty:
            st.info("No wearable data for this date.")
        else:
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=wearable["timestamp"],
                    y=wearable["heart_rate"],
                    name="Heart rate",
                    mode="lines+markers",
                    line=dict(color="#ff8cff", width=3),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=wearable["timestamp"],
                    y=wearable["stress_level"],
                    name="Stress level",
                    mode="lines+markers",
                    line=dict(color="#ffd166", width=3),
                )
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,255,255,0.04)",
                font_color="#f8edff",
                height=330,
                margin=dict(l=10, r=10, t=20, b=20),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, use_container_width=True)

    with team_col:
        st.markdown("### Meeting intensity")
        if teams.empty:
            st.info("No Teams metadata for this date.")
        else:
            teams_chart = teams.merge(
                meetings[["meeting_id", "title"]], on="meeting_id", how="left"
            )
            teams_chart["speaking_share"] = (
                teams_chart["speaking_minutes"] / teams_chart["total_minutes"]
            )
            fig = px.bar(
                teams_chart,
                x="title",
                y="speaking_share",
                color="action_items",
                color_continuous_scale=["#62d9ff", "#b56cff", "#ff8cff"],
                hover_data=["chat_messages", "interruptions", "stress_keywords"],
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,255,255,0.04)",
                font_color="#f8edff",
                height=330,
                margin=dict(l=10, r=10, t=20, b=90),
                xaxis_title="",
                yaxis_title="Speaking share",
            )
            fig.update_yaxes(tickformat=".0%")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Connected source data preview")
    preview_tabs = st.tabs(["Calendar", "Teams", "Wearable", "Check-ins"])
    with preview_tabs[0]:
        st.dataframe(meetings.drop(columns=["start_dt", "end_dt"]), use_container_width=True)
    with preview_tabs[1]:
        st.dataframe(teams, use_container_width=True)
    with preview_tabs[2]:
        st.dataframe(wearable.drop(columns=["timestamp"]), use_container_width=True)
    with preview_tabs[3]:
        st.dataframe(checkins, use_container_width=True)


if __name__ == "__main__":
    main()
