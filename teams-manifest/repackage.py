#!/usr/bin/env python3
"""Update the Teams manifest to a tunnel host and repackage the sideload zip.

Usage:  python repackage.py <tunnel-host>
Example: python repackage.py monitors-cooked-places-cuisine.trycloudflare.com

Only the manifest holds hard-coded URLs (the HTML/JS use relative paths and
window.location.origin), so this single step is all that changes when the
cloudflared quick-tunnel URL changes.
"""
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
ICONS = ["color.png", "outline.png"]
ZIP = HERE / "PawseTeamsApp.zip"


def bump(v: str) -> str:
    a, b, c = (v.split(".") + ["0", "0", "0"])[:3]
    return f"{a}.{b}.{int(c) + 1}"


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Tunnel-Host fehlt. Bsp: python repackage.py xyz.trycloudflare.com")
    host = sys.argv[1].replace("https://", "").replace("http://", "").rstrip("/")
    base = f"https://{host}"

    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    m["version"] = bump(m.get("version", "1.0.0"))
    cb = m["version"].replace(".", "")  # cache-buster so Teams reloads iframes

    for tab in m.get("staticTabs", []):
        tab["contentUrl"] = f"{base}/teamsapp/index.html?v={cb}"
        tab["websiteUrl"] = f"{base}/teamsapp/index.html?v={cb}"
    for tab in m.get("configurableTabs", []):
        tab["configurationUrl"] = f"{base}/teamsapp/config.html?v={cb}"

    keep = [d for d in m.get("validDomains", []) if "trycloudflare.com" not in d and "devtunnels.ms" not in d]
    m["validDomains"] = [host] + keep

    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(MANIFEST, "manifest.json")
        for ic in ICONS:
            z.write(HERE / ic, ic)

    print(f"OK  version={m['version']}  host={host}")
    print(f"ZIP: {ZIP}")
    print(f"tab: {base}/teamsapp/meetingpanel.html")


if __name__ == "__main__":
    main()
