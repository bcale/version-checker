#!/usr/bin/env python3
"""
Version Sync
------------
Detects the installed version of each application on this machine
and automatically updates the tracked_cycle field in applications.yaml.

Runs before checker.py in the daily cron job so EOL lookups always
reflect what is actually installed.

Usage:
    python sync_versions.py                        # uses default applications.yaml
    python sync_versions.py --config my_apps.yaml  # custom config path
    python sync_versions.py --dry-run              # detect only, do not write YAML
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

def detect_version(version_check: dict, app_name: str) -> str | None:
    """
    Detects the installed version of an app using the version_check config block.

    Supports two methods:
      - "command": runs a shell command and parses its output
      - "file":    reads a file on disk and parses its content

    Both use a regex with a single capture group to extract the version string.
    Returns the version string (e.g. "11.4.0") or None if detection fails.
    """
    method = version_check.get("method")
    regex = version_check.get("regex")

    if not method or not regex:
        print(f"[WARN] {app_name}: version_check is missing 'method' or 'regex' — skipping")
        return None

    # --- Run a shell command ---
    if method == "command":
        command = version_check.get("command")
        if not command:
            print(f"[WARN] {app_name}: version_check method is 'command' but no command is set")
            return None
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr  # some tools print to stderr
        except subprocess.TimeoutExpired:
            print(f"[ERROR] {app_name}: version check command timed out: {command}")
            return None
        except Exception as e:
            print(f"[ERROR] {app_name}: failed to run command '{command}': {e}")
            return None

    # --- Read a file ---
    elif method == "file":
        path = version_check.get("path")
        if not path:
            print(f"[WARN] {app_name}: version_check method is 'file' but no path is set")
            return None
        try:
            output = Path(path).read_text()
        except FileNotFoundError:
            print(f"[WARN] {app_name}: version file not found: {path}")
            return None
        except Exception as e:
            print(f"[ERROR] {app_name}: failed to read file '{path}': {e}")
            return None

    else:
        print(f"[WARN] {app_name}: unknown version_check method '{method}' — skipping")
        return None

    # --- Extract version with regex ---
    match = re.search(regex, output)
    if not match:
        print(f"[WARN] {app_name}: regex '{regex}' found no match in output:")
        print(f"       {output[:200].strip()}")
        return None

    return match.group(1).strip()


# ---------------------------------------------------------------------------
# Cycle derivation
# ---------------------------------------------------------------------------

def derive_cycle(version: str, eol_name: str | None) -> str:
    """
    Derives the tracked_cycle value from a full version string.

    Different products track EOL at different granularities:
      - Mattermost: major.minor  (e.g. "11.4.0" → "11.4")
      - Nextcloud:  major        (e.g. "32.0.5"  → "32")
      - Logstash:   major        (e.g. "9.3.0"   → "9")
      - Default:    major.minor

    Add more products here as needed.
    """
    parts = version.split(".")

    major_only = {"nextcloud", "logstash"}

    if eol_name and eol_name.lower() in major_only:
        return parts[0]                            # e.g. "32"
    else:
        return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]  # e.g. "11.4"


# ---------------------------------------------------------------------------
# YAML update
# ---------------------------------------------------------------------------

def update_yaml(config_path: Path, app_name: str, new_cycle: str):
    """
    Updates the tracked_cycle value for a specific app in the YAML file.
    Writes the file back in-place, preserving all other content and comments.

    Uses a targeted regex replace rather than re-serialising with PyYAML,
    which would strip comments from the file.
    """
    content = config_path.read_text()

    # Match the app's name block and replace its tracked_cycle line
    # Pattern: finds "name: <app>" then looks ahead for "tracked_cycle: <value>"
    # within the same application block (before the next "- name:" entry)
    pattern = (
        r'(- name:\s+' + re.escape(app_name) + r'.*?'
        r'tracked_cycle:\s*)(["\']?[\d.]+["\']?)'
    )
    replacement = rf'\g<1>"{new_cycle}"'

    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print(f"[WARN] {app_name}: could not find tracked_cycle in YAML to update")
        return

    config_path.write_text(new_content)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Version Sync — update tracked_cycle in YAML")
    parser.add_argument(
        "--config",
        default=Path(__file__).parent / "applications.yaml",
        help="Path to applications YAML config (default: applications.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect versions and print findings without updating the YAML",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    applications = config.get("applications", [])
    if not applications:
        print("[ERROR] No applications found in config.")
        sys.exit(1)

    print(f"Syncing versions for {len(applications)} application(s)...\n")

    updated = 0
    skipped = 0

    for app in applications:
        name = app["name"]
        eol_name = app.get("eol_name")
        current_cycle = app.get("tracked_cycle", "")
        version_check = app.get("version_check")

        # Skip apps with no version_check config (e.g. Element Web has no eol_name)
        if not version_check:
            print(f"[{name}] No version_check configured — skipping")
            skipped += 1
            continue

        # Skip apps with no eol_name — cycle has no effect without it
        if not eol_name:
            print(f"[{name}] No eol_name set — detecting version for info only")

        # Detect the installed version
        detected_version = detect_version(version_check, name)
        if not detected_version:
            print(f"[{name}] Could not detect installed version — leaving tracked_cycle unchanged")
            skipped += 1
            continue

        # Derive the cycle from the detected version
        new_cycle = derive_cycle(detected_version, eol_name)

        print(f"[{name}]")
        print(f"  Detected version : {detected_version}")
        print(f"  Derived cycle    : {new_cycle}")
        print(f"  Current cycle    : {current_cycle or '(not set)'}")

        if new_cycle == current_cycle:
            print(f"  → No change needed\n")
            continue

        if args.dry_run:
            print(f"  → [DRY RUN] Would update tracked_cycle: '{current_cycle}' → '{new_cycle}'\n")
        else:
            if eol_name:  # only write if cycle is actually used for EOL lookups
                update_yaml(config_path, name, new_cycle)
                print(f"  → Updated tracked_cycle: '{current_cycle}' → '{new_cycle}'\n")
                updated += 1
            else:
                print(f"  → Skipping YAML write (no eol_name set)\n")

    print("-" * 40)
    if args.dry_run:
        print("Dry run complete — no changes written.")
    else:
        print(f"Done. {updated} app(s) updated, {skipped} skipped.")


if __name__ == "__main__":
    main()