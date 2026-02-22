#!/usr/bin/env python3
"""
EOL & Release Tracker

By: Claude.ai, Caleb Barnes
---------------------
Monitors open source applications for:
  - New GitHub releases
  - Approaching or passed End of Life dates

Findings are posted to a new Confluence page each day.

Usage:
    python checker.py                        # uses default applications.yaml
    python checker.py --config my_apps.yaml  # custom config path
    python checker.py --dry-run              # print results, skip Confluence post
"""

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import requests
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
CONFLUENCE_URL = os.getenv("CONFLUENCE_URL")               # e.g. https://yourorg.atlassian.net/wiki
CONFLUENCE_USER = os.getenv("CONFLUENCE_USER")             # your Atlassian account email
CONFLUENCE_TOKEN = os.getenv("CONFLUENCE_TOKEN")           # Atlassian API token
CONFLUENCE_SPACE_KEY = os.getenv("CONFLUENCE_SPACE_KEY")   # e.g. "OPS" or "TEAM"
CONFLUENCE_PARENT_PAGE_ID = os.getenv("CONFLUENCE_PARENT_PAGE_ID")  # optional parent page ID

GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    **({"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}),
}

# Warn when EOL is within this many days
EOL_WARNING_THRESHOLD_DAYS = 5

# ---------------------------------------------------------------------------
# GitHub — latest release
# ---------------------------------------------------------------------------

def get_latest_release(repo: str) -> dict | None:
    """
    Fetches the latest release from a public GitHub repo.
    Returns a dict with version, date, and URL — or None on failure.
    Retries once on timeout.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    for attempt in range(2):
        try:
            response = requests.get(url, headers=GITHUB_HEADERS, timeout=20)
            response.raise_for_status()
            data = response.json()
            return {
                "version": data.get("tag_name", "unknown"),
                "published_at": data.get("published_at", "")[:10],
                "url": data.get("html_url", ""),
                "prerelease": data.get("prerelease", False),
            }
        except requests.Timeout:
            print(f"[WARN] GitHub request timed out for {repo} (attempt {attempt + 1}/2)")
        except requests.RequestException as e:
            print(f"[ERROR] GitHub API error for {repo}: {e}")
            return None
    print(f"[ERROR] GitHub request failed after 2 attempts for {repo}")
    return None

# ---------------------------------------------------------------------------
# endoflife.date — EOL lookup
# ---------------------------------------------------------------------------

def get_eol_info(product: str, cycle: str) -> dict | None:
    """
    Queries endoflife.date for a specific product/cycle.
    Uses the stable v0 API which supports individual cycle lookups:
      https://endoflife.date/api/{product}/{cycle}.json
    Falls back to fetching all cycles from v1 if v0 returns 404.
    """
    # Try v0 first — simple, direct, and proven to work
    url_v0 = f"https://endoflife.date/api/{product}/{cycle}.json"
    try:
        response = requests.get(url_v0, timeout=10)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        pass

    # Fall back to v1 — fetch all cycles and find the matching one
    url_v1 = f"https://endoflife.date/api/v1/products/{product}/"
    try:
        response = requests.get(url_v1, timeout=10)
        if response.status_code == 404:
            print(f"[WARN] Product '{product}' not found on endoflife.date")
            return None
        response.raise_for_status()
        data = response.json()

        # v1 uses "cycles" key, each entry has a "name" field
        cycles = data.get("cycles", [])
        for c in cycles:
            if str(c.get("name", "")).startswith(cycle):
                return c

        print(f"[WARN] Cycle '{cycle}' not found in '{product}'. "
              f"Available: {[c.get('name') for c in cycles[:5]]}")
        return None

    except requests.RequestException as e:
        print(f"[ERROR] endoflife.date API error for {product}: {e}")
        return None

# ---------------------------------------------------------------------------
# EOL evaluation
# ---------------------------------------------------------------------------

def evaluate_eol(eol_value, label: str = "") -> dict:
    """
    Normalises an EOL value from the API or YAML config into a standard dict.
    eol_value may be False/None (no EOL), True (EOL, no date), or "YYYY-MM-DD".
    """
    today = date.today()

    if eol_value is False or eol_value is None:
        return {"is_eol": False, "days_until_eol": None, "eol_date": None}

    if eol_value is True:
        return {"is_eol": True, "days_until_eol": 0, "eol_date": "unknown"}

    try:
        eol_date = datetime.strptime(str(eol_value), "%Y-%m-%d").date()
        days_left = (eol_date - today).days
        return {
            "is_eol": days_left <= 0,
            "days_until_eol": days_left,
            "eol_date": str(eol_value),
        }
    except ValueError:
        print(f"[WARN] Could not parse EOL date '{eol_value}' for {label}")
        return {"is_eol": False, "days_until_eol": None, "eol_date": str(eol_value)}

# ---------------------------------------------------------------------------
# Per-application check
# ---------------------------------------------------------------------------

def check_application(app: dict) -> dict:
    """
    Runs release and EOL checks for a single application config entry.
    Returns a result dict with findings and any warnings.
    """
    name = app["name"]
    tracked_cycle = str(app.get("tracked_cycle", ""))

    result = {
        "name": name,
        "installed_version": app.get("installed_version", "—"),
        "latest_release": None,
        "latest_release_date": None,
        "latest_release_url": None,
        "is_eol": False,
        "eol_date": None,
        "days_until_eol": None,
        "esr": None,
    }

    # --- Latest GitHub release ---
    repo = app.get("github_repo")
    if repo:
        release = get_latest_release(repo)
        if release:
            result["latest_release"] = release["version"]
            result["latest_release_date"] = release["published_at"]
            result["latest_release_url"] = release["url"]
        else:
            print(f"[WARN] Could not fetch GitHub release for {repo}")

    # --- EOL check via endoflife.date ---
    eol_name = app.get("eol_name")
    if eol_name and tracked_cycle:
        eol_data = get_eol_info(eol_name, tracked_cycle)
        if eol_data:
            eol_value = eol_data.get("eol")
            eol_info = evaluate_eol(eol_value, name)
            result.update(eol_info)

    # --- Optional ESR track ---
    esr_version = app.get("esr_version")
    esr_eol_date = app.get("esr_eol_date")
    if esr_version and esr_eol_date:
        esr_eol_info = evaluate_eol(esr_eol_date, f"{name} ESR")
        result["esr"] = {
            "version": esr_version,
            "eol_date": esr_eol_date,
            "is_eol": esr_eol_info["is_eol"],
            "days_until_eol": esr_eol_info["days_until_eol"],
        }

    return result

# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_results(results: list[dict]):
    """Prints a clean summary to stdout."""
    print("\n" + "=" * 60)
    print(f"  EOL & Release Tracker — {date.today().isoformat()}")
    print("=" * 60)
    for r in results:
        print(f"\n[{r['name']}]")
        if r["latest_release"]:
            print(f"  Latest release  : {r['latest_release']} ({r['latest_release_date']})")
            print(f"  Release URL     : {r['latest_release_url']}")
        if r["eol_date"]:
            print(f"  EOL date        : {r['eol_date']} ({r['days_until_eol']} days remaining)")
        else:
            print(f"  EOL date        : EOL data not provided")
        if r["esr"]:
            esr = r["esr"]
            print(f"  ESR {esr['version']}          : EOL {esr['eol_date']} ({esr['days_until_eol']} days remaining)")
    print("\n" + "=" * 60 + "\n")

# ---------------------------------------------------------------------------
# Confluence — build HTML page body
# ---------------------------------------------------------------------------

def build_confluence_html(results: list[dict]) -> str:
    """
    Renders the check results as Confluence storage-format HTML.
    Produces a summary panel at the top and a detailed table per application.
    """
    today = date.today().isoformat()
    total = len(results)

    html = f"""
<div style="background-color:#E3FCEF; border-left: 4px solid #00875A; padding: 12px 16px; margin-bottom: 16px;">
  <strong>Daily Check — {today}</strong>
  <p style="margin: 4px 0 0 0;">{total} applications tracked.</p>
</div>

<h2>Application Status</h2>
<table>
  <thead>
    <tr>
      <th>Application</th>
      <th>Currently Installed Version</th>
      <th>Latest Release</th>
      <th>Release Date</th>
      <th>EOL Date</th>
      <th>Days Until EOL</th>
    </tr>
  </thead>
  <tbody>
"""

    for r in results:
        release_link = (
            f'<a href="{r["latest_release_url"]}">{r["latest_release"]}</a>'
            if r["latest_release_url"] else r["latest_release"] or "—"
        )

        eol_display = r["eol_date"] or "EOL not provided"
        days_display = str(r["days_until_eol"]) if r["days_until_eol"] is not None else "EOL not provided"

        # Highlight row if EOL is approaching or passed
        if r["is_eol"]:
            row_colour = "#FFEBE6"   # red tint — already EOL
        elif r["days_until_eol"] is not None and r["days_until_eol"] <= EOL_WARNING_THRESHOLD_DAYS:
            row_colour = "#FFFAE6"   # yellow tint — EOL approaching
        else:
            row_colour = "#FFFFFF"   # white — all clear

        installed = r.get("installed_version") or "—"
        html += f"""
    <tr style="background-color:{row_colour};">
      <td><strong>{r['name']}</strong></td>
      <td>{installed}</td>
      <td>{release_link}</td>
      <td>{r['latest_release_date'] or '—'}</td>
      <td>{eol_display}</td>
      <td>{days_display}</td>
    </tr>"""

        # ESR as a sub-row if present
        if r["esr"]:
            esr = r["esr"]
            esr_days = str(esr["days_until_eol"]) if esr["days_until_eol"] is not None else "—"
            esr_colour = "#FFEBE6" if esr["is_eol"] else (
                "#FFFAE6" if esr["days_until_eol"] is not None and esr["days_until_eol"] <= EOL_WARNING_THRESHOLD_DAYS
                else "#FFFFFF"
            )
            html += f"""
    <tr style="background-color:{esr_colour};">
      <td><em>&nbsp;&nbsp;{r['name']} ESR {esr['version']}</em></td>
      <td>-</td>
      <td>-</td>
      <td>{esr['eol_date']}</td>
      <td>{esr_days}</td>
    """

    html += """
  </tbody>
</table>
<p><em>Release and EOL data obtained from endoflife.date and the application's Github.com repos.</em></p>
"""
    return html

# ---------------------------------------------------------------------------
# Confluence — post page
# ---------------------------------------------------------------------------

def post_to_confluence(html_body: str) -> bool:
    """
    Creates a new Confluence page for today's report.
    Returns True on success, False on failure.
    """
    required = {
        "CONFLUENCE_URL": CONFLUENCE_URL,
        "CONFLUENCE_USER": CONFLUENCE_USER,
        "CONFLUENCE_TOKEN": CONFLUENCE_TOKEN,
        "CONFLUENCE_SPACE_KEY": CONFLUENCE_SPACE_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        return False

    title = f"End of Life (EOL) & Release Report — {date.today().isoformat()}"
    api_url = f"{CONFLUENCE_URL.rstrip('/')}/rest/api/content"

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": CONFLUENCE_SPACE_KEY},
        "body": {
            "storage": {
                "value": html_body,
                "representation": "storage",
            }
        },
    }

    # Nest under a parent page if specified
    if CONFLUENCE_PARENT_PAGE_ID:
        payload["ancestors"] = [{"id": CONFLUENCE_PARENT_PAGE_ID}]

    try:
        response = requests.post(
            api_url,
            json=payload,
            auth=(CONFLUENCE_USER, CONFLUENCE_TOKEN),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        page_url = (
            CONFLUENCE_URL.rstrip("/")
            + response.json().get("_links", {}).get("webui", "")
        )
        print(f"[OK] Confluence page created: {page_url}")
        return True
    except requests.RequestException as e:
        print(f"[ERROR] Failed to post to Confluence: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"       Response: {e.response.text}")
        return False

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EOL & Release Tracker")
    parser.add_argument(
        "--config",
        default=Path(__file__).parent / "applications.yaml",
        help="Path to applications YAML config (default: applications.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run checks and print results without posting to Confluence",
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

    print(f"Checking {len(applications)} application(s)...")
    results = [check_application(app) for app in applications]

    print_results(results)

    if args.dry_run:
        print("[DRY RUN] Skipping Confluence post.")
    else:
        html = build_confluence_html(results)
        post_to_confluence(html)


if __name__ == "__main__":
    main()
