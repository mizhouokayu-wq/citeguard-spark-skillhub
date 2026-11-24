"""Capture screenshots of CiteGuard's evidence_replay.html using local headless Chromium."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME_PATH = Path(
    os.environ.get(
        "CHROME_PATH",
        str(
            Path.home()
            / ".cache"
            / "puppeteer"
            / "chrome-headless-shell"
            / "win64-131.0.6778.204"
            / "chrome-headless-shell-win64"
            / "chrome-headless-shell.exe"
        ),
    )
)


def capture_html_screenshots(html_path: Path, out_dir: Path) -> list[Path]:
    """Render evidence_replay.html in headless Chrome and capture top + lower sections."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Use chrome --screenshot for zero-dependency crisp capture at 1280x960 and taller full view
    shots: list[Path] = []
    file_url = html_path.resolve().as_uri()
    with tempfile.TemporaryDirectory(prefix="citeguard-chrome-") as tmp:
        for name, win_size in [
            ("walkthrough_overview.png", "1320,1040"),
            ("walkthrough_full.png", "1320,2550"),
        ]:
            target = out_dir / name
            cmd = [
                str(CHROME_PATH),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                f"--user-data-dir={tmp}",
                f"--window-size={win_size}",
                f"--screenshot={target}",
                file_url,
            ]
            subprocess.run(cmd, check=True, timeout=30)
            shots.append(target)
    return shots


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    html_file = base / "artifacts" / "evidence_replay.html"
    if not html_file.exists():
        html_file = base / "artifacts_dryrun" / "evidence_replay.html"
    captured = capture_html_screenshots(html_file, base / "screenshots")
    print("Captured:", [str(p) for p in captured])
