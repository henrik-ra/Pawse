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
import random
import sys
import tkinter as tk
import urllib.request
from datetime import datetime

# --- Config -----------------------------------------------------------------
API_URL = "http://localhost:8000/api/live-day"
DEFAULT_INTERVAL_MIN = 30        # minutes between pop-ups
VISIBLE_SECONDS = 8              # how long the panda stays on screen
WORK_HOURS = (8, 20)            # only appear between these local hours
JITTER_MIN = 8                   # +/- random minutes so it feels organic
CARD_W, CARD_H = 320, 142
MARGIN = 22                      # gap from screen edges
TASKBAR_PAD = 48                 # leave room above the taskbar
TRANSPARENT = "#010203"          # this colour becomes see-through (Windows)

# Theme (matches the dashboard)
BG = "#ffffff"
INK = "#232826"
INK_SOFT = "#5c6360"
RING_BG = "#e8e2d4"
GOOD, WARN, BAD = "#2ecc71", "#f4b740", "#e8553e"
PANDA_BLACK = "#1b1c1e"


# --- Data -------------------------------------------------------------------
def fetch_day() -> dict | None:
    """Pull the current scored day from the Pawse server (None if unreachable)."""
    try:
        with urllib.request.urlopen(API_URL, timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
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


# --- Drawing helpers --------------------------------------------------------
def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_panda(c: tk.Canvas, cx: float, cy: float, r: float, mood: str):
    """Draw a compact, mood-reactive panda face centred at (cx, cy)."""
    er = r * 0.42  # ear radius
    # ears
    for ex in (cx - r * 0.62, cx + r * 0.62):
        c.create_oval(ex - er, cy - r * 0.95, ex + er, cy - r * 0.95 + 2 * er,
                      fill=PANDA_BLACK, outline="")
    # head
    c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#fdfdfd", outline="#e7e2d6", width=2)
    # eye patches
    for sx in (-1, 1):
        px = cx + sx * r * 0.42
        c.create_oval(px - r * 0.30, cy - r * 0.34, px + r * 0.30, cy + r * 0.22,
                      fill=PANDA_BLACK, outline="")
    # eyes + highlight
    for sx in (-1, 1):
        px = cx + sx * r * 0.42
        c.create_oval(px - r * 0.11, cy - r * 0.16, px + r * 0.11, cy + r * 0.06,
                      fill="#101010", outline="")
        c.create_oval(px - r * 0.02, cy - r * 0.12, px + r * 0.06, cy - r * 0.04,
                      fill="#ffffff", outline="")
    # nose
    c.create_oval(cx - r * 0.12, cy + r * 0.26, cx + r * 0.12, cy + r * 0.42,
                  fill=PANDA_BLACK, outline="")
    # mouth by mood
    my = cy + r * 0.52
    if mood == "good":
        c.create_arc(cx - r * 0.26, my - r * 0.22, cx + r * 0.26, my + r * 0.22,
                     start=200, extent=140, style="arc", outline=INK, width=2)
        for sx in (-1, 1):  # blush
            c.create_oval(cx + sx * r * 0.62 - 6, cy + r * 0.30 - 4,
                          cx + sx * r * 0.62 + 6, cy + r * 0.30 + 4,
                          fill="#ffc2cf", outline="")
    elif mood == "med":
        c.create_line(cx - r * 0.18, my, cx + r * 0.18, my, fill=INK, width=2)
    else:  # bad — frown, worried brows, sweat drop
        c.create_arc(cx - r * 0.26, my, cx + r * 0.26, my + r * 0.40,
                     start=20, extent=140, style="arc", outline=INK, width=2)
        c.create_line(cx - r * 0.62, cy - r * 0.40, cx - r * 0.30, cy - r * 0.26, fill=INK, width=2)
        c.create_line(cx + r * 0.62, cy - r * 0.40, cx + r * 0.30, cy - r * 0.26, fill=INK, width=2)
        c.create_oval(cx + r * 0.86, cy - r * 0.30, cx + r * 0.86 + 8, cy - r * 0.30 + 12,
                      fill="#4aa3e0", outline="")


def draw_ring(c: tk.Canvas, cx: float, cy: float, r: float, score: int):
    c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=RING_BG, width=7)
    if score > 0:
        c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-3.6 * score,
                     style="arc", outline=ring_color(score), width=7)
    c.create_text(cx, cy, text=str(score), fill=INK, font=("Segoe UI", 20, "bold"))


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
        self.root.after(delay, self.show_once)
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
    def show_once(self):
        if self._popup is not None:
            return
        hour = datetime.now().hour
        if not (WORK_HOURS[0] <= hour < WORK_HOURS[1]):
            return
        day = fetch_day()
        if not day:
            return
        score = int(day.get("pawse_score", day.get("score", 0)) or 0)
        label = day.get("label", "")
        wearable = (day.get("data") or {}).get("wearable", {})
        steps = wearable.get("steps")
        self._build_popup(score, label, steps)

    def _build_popup(self, score: int, label: str, steps):
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
        # soft drop shadow (tkinter has no alpha, so use a solid taupe edge) + card
        round_rect(c, 9, 12, CARD_W - 3, CARD_H - 3, 22, fill="#d7d1c4", outline="")
        round_rect(c, 6, 6, CARD_W - 6, CARD_H - 9, 22, fill=BG, outline="#ece7da")

        mood = mood_for(score)
        draw_panda(c, 60, 64, 38, mood)
        draw_ring(c, CARD_W - 52, 52, 30, score)

        c.create_text(112, 28, anchor="w", text="Pawse", fill=INK, font=("Segoe UI", 13, "bold"))
        c.create_text(112, 50, anchor="w", text=label or "", fill=ring_color(score),
                      font=("Segoe UI", 10, "bold"))
        nudge = nudge_for(score, steps)
        if steps is not None:
            nudge += f"  ·  {int(steps):,} steps"
        c.create_text(20, CARD_H - 26, anchor="w", text=nudge, fill=INK_SOFT,
                      font=("Segoe UI", 9), width=CARD_W - 40)

        c.bind("<Button-1>", lambda e: self._close())

        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        self._x = sw - CARD_W - MARGIN
        self._target_y = sh - CARD_H - TASKBAR_PAD
        start_y = sh + 10
        top.geometry(f"{CARD_W}x{CARD_H}+{self._x}+{start_y}")
        self._slide_in(start_y)
        self.root.after(VISIBLE_SECONDS * 1000, self._close)

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
