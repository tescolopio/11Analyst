#!/usr/bin/env python3
"""
Sync logs from Quest headset file share to local 11TTLogs folder.

The Eleven Table Tennis app exposes a simple HTTP file share when enabled.
This script polls for new or updated logs and downloads them automatically.

Usage:
    python quest_sync.py --host 172.16.0.15:8090 --logs ./11TTLogs
    python quest_sync.py --host 172.16.0.15:8090 --logs ./11TTLogs --watch 30
    python quest_sync.py --host 172.16.0.15:8090 --logs ./11TTLogs --watch 30 --rebuild

The --watch flag enables continuous polling at the specified interval (seconds).
The --rebuild flag runs analyst.py after each sync that downloads new files.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


def get_listing(base_url: str, path: str) -> list[dict]:
    """Fetch directory listing from Quest file share."""
    url = f"{base_url}/getListing?path={urllib.parse.quote(path)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("output", [])
    except urllib.error.URLError as e:
        print(f"Error fetching listing: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing listing response: {e}")
        return []


def download_file(base_url: str, remote_path: str, local_path: Path) -> bool:
    """Download a file from Quest file share."""
    url = f"{base_url}/downloadFile?path={urllib.parse.quote(remote_path)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            content = response.read()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            return True
    except urllib.error.URLError as e:
        print(f"Error downloading {remote_path}: {e}")
        return False


def file_hash(path: Path) -> Optional[str]:
    """Compute SHA-256 hash of a local file."""
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def sync_logs(
    base_url: str,
    logs_dir: Path,
    dry_run: bool = False,
    verbose: bool = True
) -> list[str]:
    """
    Sync logs from Quest to local folder.

    Returns list of newly downloaded filenames.
    """
    remote_logs = get_listing(base_url, "logs")
    if not remote_logs:
        if verbose:
            print("No logs found on Quest or connection failed.")
        return []

    # Filter to .log files only
    log_files = [f for f in remote_logs if f.get("type") == "file" and f.get("name", "").endswith(".log")]

    if verbose:
        print(f"Found {len(log_files)} log files on Quest")

    downloaded = []
    skipped = 0

    for item in log_files:
        name = item["name"]
        remote_path = item["path"]
        remote_size = int(item.get("size", 0))
        remote_modified = int(item.get("lastModified", 0))

        local_path = logs_dir / name

        # Check if we need to download
        need_download = False
        reason = ""

        if not local_path.exists():
            need_download = True
            reason = "new"
        else:
            local_size = local_path.stat().st_size
            if local_size != remote_size:
                need_download = True
                reason = f"size changed ({local_size} -> {remote_size})"

        if need_download:
            if dry_run:
                print(f"  Would download: {name} ({reason})")
            else:
                if verbose:
                    print(f"  Downloading: {name} ({reason})...", end=" ", flush=True)
                if download_file(base_url, remote_path, local_path):
                    if verbose:
                        print(f"done ({remote_size:,} bytes)")
                    downloaded.append(name)
                else:
                    if verbose:
                        print("FAILED")
        else:
            skipped += 1

    if verbose and skipped > 0:
        print(f"  Skipped {skipped} unchanged files")

    return downloaded


def sync_settings(
    base_url: str,
    output_dir: Path,
    dry_run: bool = False,
    verbose: bool = True
) -> bool:
    """
    Sync ball machine settings from Quest.

    Returns True if settings were downloaded/updated.
    """
    remote_path = "settings/BallLauncherSettings.json"
    local_path = output_dir / "quest_BallLauncherSettings.json"

    # Get file info
    settings_list = get_listing(base_url, "settings")
    ball_launcher = next(
        (f for f in settings_list if f.get("name") == "BallLauncherSettings.json"),
        None
    )

    if not ball_launcher:
        if verbose:
            print("No BallLauncherSettings.json found on Quest")
        return False

    remote_size = int(ball_launcher.get("size", 0))

    need_download = False
    if not local_path.exists():
        need_download = True
    else:
        local_size = local_path.stat().st_size
        if local_size != remote_size:
            need_download = True

    if need_download:
        if dry_run:
            print(f"Would download ball machine settings ({remote_size:,} bytes)")
            return False

        if verbose:
            print(f"Downloading ball machine settings...", end=" ", flush=True)

        if download_file(base_url, remote_path, local_path):
            if verbose:
                print(f"done ({remote_size:,} bytes)")
            return True
        else:
            if verbose:
                print("FAILED")
            return False
    else:
        if verbose:
            print("Ball machine settings unchanged")
        return False


def run_analyst(output_dir: Path, logs_dir: Path, player_id: str, verbose: bool = True) -> bool:
    """Run analyst.py to rebuild analysis."""
    script_dir = Path(__file__).parent
    analyst_path = script_dir / "analyst.py"

    if not analyst_path.exists():
        print(f"Error: analyst.py not found at {analyst_path}")
        return False

    cmd = [
        sys.executable,
        str(analyst_path),
        "--logs", str(logs_dir),
        "--output", str(output_dir),
        "--player-id", player_id
    ]

    if verbose:
        print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=not verbose)
        return result.returncode == 0
    except Exception as e:
        print(f"Error running analyst: {e}")
        return False


def watch_loop(
    base_url: str,
    logs_dir: Path,
    output_dir: Path,
    interval: int,
    rebuild: bool,
    player_id: Optional[str],
    verbose: bool = True
):
    """Continuous sync loop."""
    print(f"Watching for new logs every {interval} seconds. Press Ctrl+C to stop.")
    print(f"Quest file share: {base_url}")
    print(f"Local logs folder: {logs_dir}")
    if rebuild:
        print(f"Auto-rebuild enabled (player ID: {player_id})")
    print()

    try:
        while True:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] Checking for updates...")

            downloaded = sync_logs(base_url, logs_dir, verbose=verbose)

            if downloaded and rebuild and player_id:
                print(f"Downloaded {len(downloaded)} new logs, rebuilding analysis...")
                run_analyst(output_dir, logs_dir, player_id, verbose=verbose)
            elif downloaded:
                print(f"Downloaded {len(downloaded)} new logs")
            else:
                print("No new logs")

            print()
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopped watching.")


def main():
    parser = argparse.ArgumentParser(
        description="Sync Eleven Table Tennis logs from Quest file share"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Quest file share address (e.g., 172.16.0.15:8090)"
    )
    parser.add_argument(
        "--logs",
        type=Path,
        default=Path("./11TTLogs"),
        help="Local logs directory (default: ./11TTLogs)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./output"),
        help="Output directory for analysis (default: ./output)"
    )
    parser.add_argument(
        "--player-id",
        default="1909208",
        help="Player ID for analysis rebuild (default: 1909208)"
    )
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECONDS",
        help="Watch mode: poll for changes every N seconds"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Run analyst.py after downloading new logs"
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Also sync ball machine settings"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output"
    )

    args = parser.parse_args()

    # Normalize host URL
    host = args.host
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    base_url = host.rstrip("/")

    # Ensure logs directory exists
    args.logs.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)

    verbose = not args.quiet

    if args.watch:
        watch_loop(
            base_url=base_url,
            logs_dir=args.logs,
            output_dir=args.output,
            interval=args.watch,
            rebuild=args.rebuild,
            player_id=args.player_id,
            verbose=verbose
        )
    else:
        # One-shot sync
        if verbose:
            print(f"Syncing from {base_url}")
            print(f"Logs directory: {args.logs}")
            print()

        downloaded = sync_logs(
            base_url=base_url,
            logs_dir=args.logs,
            dry_run=args.dry_run,
            verbose=verbose
        )

        if args.settings:
            sync_settings(
                base_url=base_url,
                output_dir=args.output,
                dry_run=args.dry_run,
                verbose=verbose
            )

        if downloaded and args.rebuild and not args.dry_run:
            print()
            run_analyst(args.output, args.logs, args.player_id, verbose=verbose)

        if verbose:
            print()
            if downloaded:
                print(f"Downloaded {len(downloaded)} log(s)")
            else:
                print("No new logs to download")


if __name__ == "__main__":
    import urllib.parse
    main()
