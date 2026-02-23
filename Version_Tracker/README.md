# EOL & Release Tracker

Inspects currently installed applications on the engine, then monitors open source applications for new GitHub releases and approaching End of Life (EOL) dates using endoflife.date. Runs daily via a cron job, posting a formatted report to a new Confluence page each day.

---

## Project Structure

```
eol-tracker/
│
├── sync_versions.py      # Finds currently installed app versions, then updates applications.yaml
|── applications.yaml     # Config — defines which apps to track, along with currently installed versions
|── checker.py            # Main script — runs release and EOL checks and posts to Confluence
├── requirements.txt      # Python dependencies
├── .env                  # Local secrets (Never to be committed. Currently using Caleb's personal tokens)
├── .env.example          # Safe template for .env — commit this
├── .gitignore
└── README.md
```

---

## How It Works

Each day the scripts do the following:

1. sync_versions.py hunts for services listed in `applications.yaml` for current installation versions. Updates `applications.yaml`
2. checker.py Reads `applications.yaml` to get the list of tracked applications
2. checker.py queries the **GitHub Releases API** to find each app's latest release
3. Then, checker.py queries **endoflife.date** to check EOL status for the tracked version cycle. Certain applications don't have EOL data here
4. Prints a summary to stdout
5. Posts a report as a new page in Confluence

---

### To clone and open the project

```bash
git clone <your-repo-url> eol-tracker
cd eol-tracker
code .
```

### Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Yes | Raises GitHub API rate limit from 60 to 5,000 requests/hour.
| `CONFLUENCE_URL` | Yes | Organization's Atlassian base URL, e.g. `https://yourorg.atlassian.net/wiki` |
| `CONFLUENCE_USER` | Yes | Organization's Atlassian account email address/identifier |
| `CONFLUENCE_TOKEN` | Yes | Organization's Atlassian API token |
| `CONFLUENCE_SPACE_KEY` | Yes | The key of the Confluence space where pages will be created, e.g. `OPS` |
| `CONFLUENCE_PARENT_PAGE_ID` | Optional | Page ID to nest daily reports under. Find it in the page URL in Confluence |


---

## Running the Script

```bash
# Dry run — checks everything and prints results, no Confluence post
python checker.py --dry-run

# Full run — checks and posts to Confluence
python checker.py

# Use a different config file
python checker.py --config staging_apps.yaml
```

---

## Confluence Output

Each daily run creates a new page titled:

```
End of Life (EOL) & Release Report — YYYY-MM-DD
```

If `CONFLUENCE_PARENT_PAGE_ID` is set, all daily pages are nested under that parent page, keeping your space organised over time.

---

## Cron Setup

Edit your crontab with `crontab -e`:

```bash
# Run every day at 7:00 AM
0 7 * * * cd /path/to/eol-tracker && .venv/bin/python checker.py
```

Using `.venv/bin/python` ensures cron uses the correct interpreter and installed dependencies.

---

## Adding a New Application

Open `applications.yaml` and add a new entry:

```yaml
  - name: Application name
    installed_version: ""
    eol_name: "name-listed-on-endoflife.date" # product slug on endoflife.date (if listed)
    github_repo: owner/repo
    tracked_cycle: "3.2"      # major.minor cycle for EOL lookups
    version_check:
      method: "" #either a command or a file. We will probably only use command.
      command: "" #command to find app's version number
      regex: "" #regex to pull number from command output
    notes: Any useful context for your team
```

To check if your app is listed on endoflife.date:
```
https://endoflife.date/api/all.json
```

---

## EOL Warning Threshold

By default the script warns when EOL is **within 90 days**. To change this, edit the constant near the top of `checker.py`:

```python
EOL_WARNING_THRESHOLD_DAYS = 90
```