#!/usr/bin/env python3
"""
Version Sync
------------
Detects the installed version of each application and automatically
updates the tracked_cycle field in applications.yaml.

Runs before checker.py in the daily cron job so EOL lookups always
reflect what is actually installed.

Usage:
    python sync_versions.py                        # uses default applications.yaml
    python sync_versions.py --config my_apps.yaml  # custom config path
    python sync_versions.py --dry-run              # detect only, do not write YAML
"""

import argparse
import platform
import re
import subprocess
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

IS_WINDOWS = platform.system() == "Windows"


def resolve_path(linux_path: str) -> str:
    """
    On Windows, translates a Linux-style path to the WSL network path.
    e.g. "/opt/mattermost/version.txt" -> "\\\\wsl$\\Ubuntu\\opt\\mattermost\\version.txt"
    On Linux/macOS, returns the path unchanged.
    """
    if IS_WINDOWS and linux_path.startswith("/"):
        windows_path = linux_path.replace("/", "\\")
        return f"\\\\wsl$\\Ubuntu{windows_path}"
    return linux_path


def resolve_command(command: str) -> str:
    """
    On Windows, prepends "wsl --" to Linux shell commands.
    PowerShell commands are left unchanged.
    On Linux/macOS, returns the command unchanged.
    """
    if IS_WINDOWS and not command.lower().startswith("powershell"):
        return f"wsl -- {command}"
    return command


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
        print(f"[WARN] {app_name}: version_check missing 'method' or 'regex' -- skipping")
        return None

    output = None

    # --- Run a shell command ---
    if method == "command":
        command = version_check.get("command")
        if not command:
            print(f"[WARN] {app_name}: method is 'command' but no command is set")
            return None

        command = resolve_command(command)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            print(f"[ERROR] {app_name}: command timed out: {command}")
            return None
        except Exception as e:
            print(f"[ERROR] {app_name}: failed to run command: {e}")
            return None

    # --- Read a file ---
    elif method == "file":
        raw_path = version_check.get("path")
        if not raw_path:
            print(f"[WARN] {app_name}: method is 'file' but no path is set")
            return None

        resolved = resolve_path(raw_path)

        try:
            output = Path(resolved).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"[WARN] {app_name}: version file not found: {resolved}")
            return None
        except Exception as e:
            print(f"[ERROR] {app_name}: failed to read file '{resolved}': {e}")
            return None

    else:
        print(f"[WARN] {app_name}: unknown method '{method}' -- skipping")
        return None

    # --- Extract version with regex ---
    match = re.search(regex, output)
    if not match:
        print(f"[WARN] {app_name}: regex found no match in output:")
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
      - Mattermost: major.minor  (e.g. "11.4.0" -> "11.4")
      - Nextcloud:  major        (e.g. "32.0.5"  -> "32")
      - Logstash:   major        (e.g. "9.3.0"   -> "9")
      - Default:    major.minor

    Add more products to major_only as needed.
    """
    parts = version.split(".")
    major_only = {"nextcloud", "logstash"}

    if eol_name and eol_name.lower() in major_only:
        return parts[0]
    else:
        return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]


# ---------------------------------------------------------------------------
# YAML update
# ---------------------------------------------------------------------------

def update_yaml(config_path: Path, app_name: str, new_cycle: str):
    """
    Updates the tracked_cycle value for a specific app in the YAML file,
    preserving all comments and formatting.

    Uses targeted regex replacement rather than re-serialising with PyYAML,
    which would strip all comments from the file.
    """
    content = config_path.read_text(encoding="utf-8")

    pattern = (
        r'(- name:\s+' + re.escape(app_name) + r'.*?'
        r'tracked_cycle:\s*)(["\']?[\d.]+["\']?)'
    )
    replacement = rf'\g<1>"{new_cycle}"'
    new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

    if count == 0:
        print(f"[WARN] {app_name}: could not find tracked_cycle in YAML -- was it removed?")
        return

    config_path.write_text(new_content, encoding="utf-8")


def update_installed_version(config_path: Path, app_name: str, version: str):
    """
    Writes the detected installed version back to the YAML as installed_version.
    Adds the field if it doesn't exist, updates it if it does.
    """
    content = config_path.read_text(encoding="utf-8")

    # If installed_version already exists for this app, update it
    pattern_update = (
        r'(- name:\s+' + re.escape(app_name) + r'.*?'
        r'installed_version:\s*)[^\n]*'
    )
    replacement_update = rf'\g<1>"{version}"'
    new_content, count = re.subn(pattern_update, replacement_update, content, flags=re.DOTALL)

    if count > 0:
        config_path.write_text(new_content, encoding="utf-8")
        return

    # If installed_version doesn't exist yet, insert it after the name line
    pattern_insert = r'(- name:\s+' + re.escape(app_name) + r'\s*\n)'
    replacement_insert = rf'\g<1>    installed_version: "{version}"\n'
    new_content, count = re.subn(pattern_insert, replacement_insert, content)

    if count == 0:
        print(f"[WARN] {app_name}: could not write installed_version to YAML")
        return

    config_path.write_text(new_content, encoding="utf-8")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Version Sync -- update tracked_cycle in YAML")
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

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    applications = config.get("applications", [])
    if not applications:
        print("[ERROR] No applications found in config.")
        sys.exit(1)

    print(f"Running on: {'Windows' if IS_WINDOWS else platform.system()}")
    print(f"Syncing versions for {len(applications)} application(s)...\n")

    updated = 0
    skipped = 0

    for app in applications:
        name          = app["name"]
        eol_name      = app.get("eol_name")
        current_cycle = str(app.get("tracked_cycle", ""))
        version_check = app.get("version_check")

        if not version_check:
            print(f"[{name}] No version_check configured -- skipping")
            skipped += 1
            continue

        if not eol_name:
            print(f"[{name}] No eol_name set -- detecting version for info only")

        detected_version = detect_version(version_check, name)
        if not detected_version:
            print(f"[{name}] Could not detect installed version -- tracked_cycle unchanged\n")
            skipped += 1
            continue

        # Always write the detected version back to YAML for checker.py to use
        if not args.dry_run:
            update_installed_version(config_path, name, detected_version)

        new_cycle = derive_cycle(detected_version, eol_name)

        print(f"[{name}]")
        print(f"  Detected version : {detected_version}")
        print(f"  Derived cycle    : {new_cycle}")
        print(f"  Current cycle    : {current_cycle or '(not set)'}")

        if new_cycle == current_cycle:
            print(f"  -> No change needed\n")
            continue

        if args.dry_run:
            print(f"  -> [DRY RUN] Would update: '{current_cycle}' -> '{new_cycle}'\n")
        else:
            if eol_name:
                update_yaml(config_path, name, new_cycle)
                print(f"  -> Updated tracked_cycle: '{current_cycle}' -> '{new_cycle}'\n")
                updated += 1
            else:
                print(f"  -> Skipping YAML write (no eol_name)\n")

    print("-" * 40)
    if args.dry_run:
        print("Dry run complete -- no changes written.")
    else:
        print(f"Done. {updated} app(s) updated, {skipped} skipped.")


if __name__ == "__main__":
    main()