"""Pawse Pet — a tiny desktop companion.

A little panda slides up from the bottom-right of your screen every so often,
shows your current Pawse Score with a gentle nudge, then tidies itself away.
It runs quietly in the background and reuses the data from your Pawse server.

Run it (server should be running on http://localhost:8000):

    py desktop/pawse_pet.py            # normal: pops up on a timer
    py desktop/pawse_pet.py --now      # show one popup right away (for testing)
    py desktop/pawse_pet.py --interval 15   # minutes between pop-ups

Build a standalone Windows .exe:

    pip install pyinstaller
    pyinstaller --onefile --noconsole --name PawsePet desktop/pawse_pet.py
    # -> dist/PawsePet.exe   (double-click to run; add to the Startup folder
    #    shell:startup to launch it automatically at login)

Optional system-tray icon (Show now / Quit):  pip install pystray Pillow
The popup works fine without it; the tray just adds a clean way to quit.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

# --- Config -----------------------------------------------------------------
# The pet reads the cloud dashboard by default, so it works without a local
# server. Override with the PAWSE_API_URL environment variable.
_API_BASE = os.environ.get(
    "PAWSE_API_URL",
    "https://ca-pawse-2ysupe36zqlhi.redstone-da7928c5.swedencentral.azurecontainerapps.io",
).rstrip("/")
API_URL = f"{_API_BASE}/api/live-day"
DEFAULT_INTERVAL_MIN = 30        # minutes between pop-ups
VISIBLE_SECONDS = 12             # how long the panda stays on screen
WORK_HOURS = (8, 20)            # only appear between these local hours
JITTER_MIN = 8                   # +/- random minutes so it feels organic
CARD_W, CARD_H = 360, 212
MARGIN = 22                      # gap from screen edges
TASKBAR_PAD = 48                 # leave room above the taskbar
TRANSPARENT = "#010203"          # this colour becomes see-through (Windows)

# Optional per-mood panda PNGs (panda_good/_med/_bad.png) override the drawing.
PANDA_IMAGE_DIR = Path(__file__).resolve().parent / "assets"

# Theme — pastel purple card with pastel blue accent elements.
BG = "#ece7fb"          # pastel purple card surface
SURFACE = "#d9e5fc"     # pastel blue for chips / badges / buttons
CARD_EDGE = "#d8ccf2"   # soft purple card outline
SHADOW = "#ccc0ee"      # purple-tinted drop shadow
DIVIDER = "#cdd9f2"     # pastel blue hairline
INK = "#232826"
INK_SOFT = "#d97aa9"     # pastel pink — chip text & close mark
RING_BG = "#e3dcf6"
GOOD, WARN, BAD = "#6f9eea", "#9a7fe0", "#e87ab0"
BRAND = "#6c5ab6"        # deep pastel purple for the wordmark

# Panda palette (purple fur, pink cheeks).
PANDA_FUR = "#c3b2ee"
PANDA_EDGE = "#b6a6e4"
PANDA_FACE = "#fbfaff"
CHEEK = "#f6b6d2"
HP_BLUE = "#9cc0f3"
EYE = "#3b3550"


# --- Data -------------------------------------------------------------------
# Try the configured API first, then fall back to a local server if it's running.
FALLBACK_URLS = [API_URL, "http://localhost:8000/api/live-day"]


def fetch_day() -> dict | None:
    """Pull the current scored day from the Pawse server (None if all unreachable)."""
    last_err: Exception | None = None
    for url in dict.fromkeys(FALLBACK_URLS):  # de-dupe, keep order
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - try the next source
            last_err = exc
    if last_err is not None:
        print(f"[pawse-pet] could not reach Pawse API ({last_err}); showing offline card.")
    return None


def mood_for(score: int) -> str:
    return "bad" if score >= 70 else "med" if score >= 40 else "good"


def ring_color(score: int) -> str:
    return BAD if score >= 70 else WARN if score >= 40 else GOOD


def nudge_for(score: int, steps) -> str:
    if score >= 70:
        return "Heavy day — time to pawse."
    if score >= 40:
        return "A short walk would help."
    return "Nice flow — keep it up!"


def fetch_top_action() -> dict | None:
    """Top reschedule recommendation for today (None if the endpoint is absent)."""
    try:
        with urllib.request.urlopen(f"{_API_BASE}/api/recommendations", timeout=6) as resp:
            recs = json.loads(resp.read().decode("utf-8")).get("recommendations", [])
            return recs[0] if recs else None
    except Exception:
        return None


def action_nudge(action: dict) -> str:
    """Short, clickable nudge text for a reschedule recommendation."""
    title = action.get("title", "Meeting")
    to, end = action.get("to"), action.get("end")
    if action.get("type") in ("protect_focus", "protect_lunch"):
        return f"Protect {title.lower()} {to}–{end}  →"
    return f"Move “{title}” to {to}  →"


# --- Drawing helpers --------------------------------------------------------
def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_panda(c: tk.Canvas, cx: float, cy: float, r: float, mood: str):
    """A compact, modern panda whose face reacts to the day's mood.

    good -> smiling eyes + grin, med -> calm, bad -> tired droopy eyes + "Zzz".
    Styled in the pastel palette, echoing the logo's purple fur and pink cheeks.
    """
    # Ears (pastel purple).
    er = r * 0.46
    for ex in (cx - r * 0.64, cx + r * 0.64):
        c.create_oval(ex - er, cy - r * 1.00, ex + er, cy - r * 1.00 + 2 * er,
                      fill=PANDA_FUR, outline="")
    # Head (near-white).
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=PANDA_FACE, outline=PANDA_EDGE, width=2)
    # Eye patches (pastel purple).
    for sx in (-1, 1):
        px = cx + sx * r * 0.40
        c.create_oval(px - r * 0.30, cy - r * 0.34, px + r * 0.30, cy + r * 0.22,
                      fill=PANDA_FUR, outline="")
    # Cheeks (a little pink blush, always).
    for sx in (-1, 1):
        bx = cx + sx * r * 0.60
        c.create_oval(bx - 5, cy + r * 0.24 - 4, bx + 5, cy + r * 0.24 + 4,
                      fill=CHEEK, outline="")
    # Nose.
    c.create_oval(cx - r * 0.11, cy + r * 0.20, cx + r * 0.11, cy + r * 0.35,
                  fill=EYE, outline="")

    # --- Mood-reactive eyes + mouth ---
    my = cy + r * 0.52
    if mood == "good":
        # Smiling (closed) eyes and a wide grin.
        for sx in (-1, 1):
            px = cx + sx * r * 0.40
            c.create_arc(px - r * 0.16, cy - r * 0.10, px + r * 0.16, cy + r * 0.16,
                         start=200, extent=140, style="arc", outline=EYE, width=2)
        c.create_arc(cx - r * 0.26, my - r * 0.24, cx + r * 0.26, my + r * 0.22,
                     start=200, extent=140, style="arc", outline=EYE, width=2)
    elif mood == "med":
        # Calm round eyes + a small neutral mouth.
        for sx in (-1, 1):
            px = cx + sx * r * 0.40
            c.create_oval(px - r * 0.10, cy - r * 0.10, px + r * 0.10, cy + r * 0.12,
                          fill=EYE, outline="")
        c.create_line(cx - r * 0.16, my, cx + r * 0.16, my, fill=EYE, width=2)
    else:  # bad — tired / exhausted: droopy half-closed eyes, under-eye bags, a weary sigh.
        for sx in (-1, 1):
            px = cx + sx * r * 0.40
            c.create_arc(px - r * 0.16, cy - r * 0.12, px + r * 0.16, cy + r * 0.14,
                         start=20, extent=140, style="arc", outline=EYE, width=2)
            c.create_arc(px - r * 0.13, cy + r * 0.04, px + r * 0.13, cy + r * 0.22,
                         start=200, extent=140, style="arc", outline=PANDA_EDGE, width=1)
        c.create_line(cx - r * 0.16, my + r * 0.04, cx + r * 0.16, my + r * 0.04,
                      fill=EYE, width=2)
        for (dx, dy, sz) in ((0.66, -0.52, 7), (0.92, -0.80, 8), (1.20, -1.08, 10)):
            c.create_text(cx + r * dx, cy + r * dy, text="z", fill=EYE,
                          font=("Segoe UI", sz, "bold"))


# Cache resized Tk images so the PNG is only read from disk once per size.
_PANDA_CACHE: dict[tuple[str, int], object] = {}


def panda_image(mood: str, r: float):
    """Optional mood-specific panda PNG, or None to draw the panda instead.

    Looks for panda_good/_med/_bad.png in desktop/assets/. When none exists
    (the default), returns None so the expressive vector panda is drawn.
    """
    key = (mood, int(r))
    if key in _PANDA_CACHE:
        return _PANDA_CACHE[key]
    result = None
    try:
        from PIL import Image, ImageTk

        path = next(
            (p for p in (PANDA_IMAGE_DIR / f"panda_{mood}.png",) if p.exists()),
            None,
        )
        if path is not None:
            img = Image.open(path).convert("RGBA")
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:  # older Pillow
                resample = Image.LANCZOS
            tw = max(1, int(2.6 * r))
            th = max(1, int(img.height * tw / img.width))
            result = ImageTk.PhotoImage(img.resize((tw, th), resample))
    except Exception:
        result = None
    _PANDA_CACHE[key] = result
    return result


def draw_ring(c: tk.Canvas, cx: float, cy: float, r: float, score: int):
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=RING_BG, width=7)
    if score > 0:
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-3.6 * score,
                     style="arc", outline=ring_color(score), width=7)
    c.create_text(cx, cy, text=str(score), fill=INK, font=("Segoe UI", 20, "bold"))


def draw_progress_ring(c: tk.Canvas, cx: float, cy: float, r: float, score: int, width: int = 7):
    """A mood-coloured progress ring with rounded caps (the panda sits inside)."""
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=RING_BG, width=width)
    if score <= 0:
        return
    col = ring_color(score)
    extent = -3.6 * min(score, 100)
    c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=extent,
                 style="arc", outline=col, width=width)
    cap = width / 2
    c.create_oval(cx - cap, cy - r - cap, cx + cap, cy - r + cap, fill=col, outline="")
    ang = math.radians(90 + extent)
    ex, ey = cx + r * math.cos(ang), cy - r * math.sin(ang)
    c.create_oval(ex - cap, ey - cap, ex + cap, ey + cap, fill=col, outline="")


def draw_pill(c: tk.Canvas, x_right: float, cy: float, text: str, fg: str, bg: str) -> None:
    """A small rounded status pill, right-aligned to ``x_right``."""
    f = tkfont.Font(family="Segoe UI", size=8, weight="bold")
    pad = 9
    x1 = x_right - (f.measure(text) + 2 * pad)
    round_rect(c, x1, cy - 10, x_right, cy + 10, 10, fill=bg, outline="")
    c.create_text(x1 + pad, cy, anchor="w", text=text, fill=fg, font=f)


def draw_stat_pill(c: tk.Canvas, x: float, cy: float, text: str, fg: str, bg: str,
                   size: int = 9) -> float:
    """A left-aligned rounded pill; returns its right-edge x for chaining."""
    f = tkfont.Font(family="Segoe UI", size=size, weight="bold")
    pad = 11
    w = f.measure(text) + 2 * pad
    round_rect(c, x, cy - 13, x + w, cy + 13, 13, fill=bg, outline="")
    c.create_text(x + pad, cy, anchor="w", text=text, fill=fg, font=f)
    return x + w


# --- The pet ----------------------------------------------------------------
class PawsePet:
    def __init__(self, interval_min: int):
        self.interval_min = interval_min
        self.root = tk.Tk()
        self.root.withdraw()
        self._popup: tk.Toplevel | None = None
        self._closing = False

    # scheduling -------------------------------------------------------------
    def start(self, show_now: bool):
        delay = 1500 if show_now else 4000
        self.root.after(delay, lambda: self.show_once(force=show_now))
        self._schedule_next()
        self.root.mainloop()

    def _schedule_next(self):
        jitter = random.randint(-JITTER_MIN, JITTER_MIN)
        minutes = max(2, self.interval_min + jitter)
        self.root.after(int(minutes * 60_000), self._on_timer)

    def _on_timer(self):
        self.show_once()
        self._schedule_next()

    # popup ------------------------------------------------------------------
    def show_once(self, force: bool = False):
        if self._popup is not None:
            return
        if not force:
            hour = datetime.now().hour
            if not (WORK_HOURS[0] <= hour < WORK_HOURS[1]):
                return
        day = fetch_day()
        if not day:
            if not force:
                return
            # Forced (e.g. --now): still show the pet with an offline card.
            day = {"pawse_score": 0, "label": "offline", "data": {}}
        score = int(day.get("pawse_score", day.get("score", 0)) or 0)
        label = day.get("label", "")
        wearable = (day.get("data") or {}).get("wearable", {})
        self._build_popup(score, label, wearable)

    def _build_popup(self, score: int, label: str, wearable: dict):
        top = tk.Toplevel(self.root)
        self._popup = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass  # non-Windows: falls back to a rectangular window
        top.configure(bg=TRANSPARENT)

        c = tk.Canvas(top, width=CARD_W, height=CARD_H, bg=TRANSPARENT, highlightthickness=0)
        c.pack()

        mood = mood_for(score)
        accent = ring_color(score)
        steps = wearable.get("steps")
        hr = wearable.get("hr_avg") or wearable.get("resting_hr")
        azm = wearable.get("azm_total")
        if azm is None:
            azm = wearable.get("active_minutes")

        # soft drop shadow + pastel card
        round_rect(c, 10, 13, CARD_W - 3, CARD_H - 3, 26, fill=SHADOW, outline="")
        round_rect(c, 6, 6, CARD_W - 6, CARD_H - 9, 26, fill=BG, outline=CARD_EDGE)

        # panda tucked into the top-left; its face reacts to the day
        self._draw_panda_on(c, 50, 44, 26, mood)

        # score ring, top-right
        draw_ring(c, CARD_W - 58, 52, 24, score)

        # close (X) button, top-right corner
        bx, by, br = CARD_W - 20, 18, 9
        c.create_oval(bx - br, by - br, bx + br, by + br, fill=SURFACE,
                      outline=CARD_EDGE, tags=("close",))
        c.create_text(bx, by, text="\u2715", fill=INK_SOFT,
                      font=("Segoe UI", 8, "bold"), tags=("close",))

        # brand wordmark + status badge
        c.create_text(96, 34, anchor="w", text="Pawse", fill=BRAND,
                      font=("Segoe UI", 14, "bold"))
        self._badge(c, 96, 58, (label or "").upper(), accent)

        # hairline divider under the header
        c.create_line(20, 82, CARD_W - 20, 82, fill=DIVIDER)

        # the most important metrics, as pastel chips
        chips = []
        if steps is not None:
            chips.append(f"{int(steps):,} steps")
        if hr:
            chips.append(f"{int(hr)} bpm")
        if azm is not None:
            chips.append(f"{int(azm)} active min")
        x = 22
        for chip in chips[:3]:
            x = self._chip(c, x, 104, chip)
            if x > CARD_W - 40:
                break

        # nudge — actionable when Pawse has a concrete suggestion, else a gentle tip
        action = fetch_top_action()
        if action:
            c.create_text(22, 128, anchor="nw", text=action_nudge(action),
                          fill=BRAND, font=("Segoe UI", 12, "bold"),
                          width=CARD_W - 44, tags=("action",))
            # Click opens the full dashboard (the Rebalance card lives there).
            c.tag_bind("action", "<Button-1>",
                       lambda e: (webbrowser.open(_API_BASE), self._close()))
        else:
            c.create_text(22, 128, anchor="nw", text=nudge_for(score, steps),
                          fill=INK, font=("Segoe UI", 12), width=CARD_W - 44)

        # footer — opens the dashboard
        c.create_text(CARD_W - 22, CARD_H - 20, anchor="e",
                      text="Open dashboard  \u2192", fill=accent,
                      font=("Segoe UI", 8, "bold"), tags=("dash",))

        c.tag_bind("close", "<Button-1>", lambda e: self._close())
        c.tag_bind("dash", "<Button-1>", lambda e: (webbrowser.open(_API_BASE), self._close()))

        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        self._x = sw - CARD_W - MARGIN
        self._target_y = sh - CARD_H - TASKBAR_PAD
        start_y = sh + 10
        top.geometry(f"{CARD_W}x{CARD_H}+{self._x}+{start_y}")
        self._slide_in(start_y)
        self.root.after(VISIBLE_SECONDS * 1000, self._close)

    def _draw_panda_on(self, c: tk.Canvas, cx: float, cy: float, r: float, mood: str):
        img = panda_image(mood, r)
        if img is not None:
            self._panda_img = img  # keep a reference so Tk doesn't garbage-collect it
            c.create_image(cx, cy, image=img)
        else:
            draw_panda(c, cx, cy, r, mood)

    def _chip(self, c: tk.Canvas, x: float, y: float, text: str) -> float:
        """Draw a rounded metric pill at (x, y) and return the next start x."""
        pad = 12
        t = c.create_text(x + pad, y, anchor="w", text=text, fill=INK_SOFT,
                          font=("Segoe UI", 11, "bold"))
        right = c.bbox(t)[2] + pad
        rect = round_rect(c, x, y - 15, right, y + 15, 15, fill=SURFACE, outline="")
        c.tag_lower(rect, t)
        return right + 8

    def _badge(self, c: tk.Canvas, x: float, y: float, text: str, color: str) -> None:
        """Draw a small tinted status badge (e.g. the strain label)."""
        if not text:
            return
        pad = 9
        t = c.create_text(x + pad, y, anchor="w", text=text, fill=color,
                          font=("Segoe UI", 8, "bold"))
        rect = round_rect(c, x, y - 11, c.bbox(t)[2] + pad, y + 11, 11,
                          fill=SURFACE, outline="")
        c.tag_lower(rect, t)

    def _slide_in(self, y: int):
        if self._popup is None:
            return
        if y > self._target_y:
            y = max(self._target_y, y - 22)
            self._popup.geometry(f"{CARD_W}x{CARD_H}+{self._x}+{y}")
            self.root.after(12, lambda: self._slide_in(y))

    def _close(self):
        top = self._popup
        if top is None:
            return
        self._popup = None
        try:
            top.destroy()
        except tk.TclError:
            pass

    def quit(self):
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


# --- Optional system-tray icon ---------------------------------------------
def try_start_tray(pet: "PawsePet"):
    try:
        import threading

        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        print("[pawse-pet] running without tray (pip install pystray Pillow to add one). "
              "Quit via Task Manager.")
        return

    img = Image.new("RGB", (64, 64), "#3fa34d")
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 48, 48), fill="white")
    d.ellipse((22, 26, 30, 34), fill="black")
    d.ellipse((34, 26, 42, 34), fill="black")

    def _show(icon, item):
        pet.root.after(0, pet.show_once)

    def _quit(icon, item):
        icon.stop()
        pet.root.after(0, pet.quit)

    menu = pystray.Menu(
        pystray.MenuItem("Show now", _show),
        pystray.MenuItem("Quit", _quit),
    )
    icon = pystray.Icon("PawsePet", img, "Pawse Pet", menu)
    threading.Thread(target=icon.run, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description="Pawse Pet — desktop panda companion")
    ap.add_argument("--now", action="store_true", help="show one popup right away")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MIN,
                    help="minutes between pop-ups")
    args = ap.parse_args()

    pet = PawsePet(interval_min=args.interval)
    try_start_tray(pet)
    pet.start(show_now=args.now)


if __name__ == "__main__":
    main()
