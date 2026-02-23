# EOL & Release Tracker

Inspects currently installed applications on the engine, then monitors open source applications for new GitHub releases and approaching End of Life (EOL) dates using endoflife.date. Runs daily via a cron job, posting a formatted report to a new Confluence page each day.

---

## Project Structure

```
eol-tracker/
│
├── sync_versions.py      # Finds currently installed app versions, then updates applications.yaml
|── checker.py            # Main script — runs release and EOL checks and posts to Confluence
├── applications.yaml     # Config — defines which apps to track, along with currently installed versions
├── requirements.txt      # Python dependencies
├── .env                  # Local secrets ( never to be committed)
├── .env.example          # Safe template for .env — commit this
├── .gitignore
└── README.md
```

---

## How It Works

Each day the script:

1. 
2. Reads `applications.yaml` to get the list of tracked applications
2. Queries the **GitHub Releases API** to find each app's latest release
3. Queries **endoflife.date** to check EOL status for the tracked version cycle
4. Prints a summary to stdout
5. Posts a colour-coded report as a new page in Confluence

---

## VS Code Setup

### 1. Clone and open the project

```bash
git clone <your-repo-url> eol-tracker
cd eol-tracker
code .
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows
pip install -r requirements.txt
```


### 4. Debug configuration

Create `.vscode/launch.json` to run and debug with `F5`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run Tracker (dry-run)",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/checker.py",
      "args": ["--dry-run"],
      "envFile": "${workspaceFolder}/.env",
      "console": "integratedTerminal"
    }
  ]
}
```

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | Recommended | Raises GitHub API rate limit from 60 to 5,000 requests/hour. Generate at: github.com → Settings → Developer settings → Personal access tokens |
| `CONFLUENCE_URL` | Yes | Your Atlassian base URL, e.g. `https://yourorg.atlassian.net/wiki` |
| `CONFLUENCE_USER` | Yes | Your Atlassian account email address |
| `CONFLUENCE_TOKEN` | Yes | Atlassian API token. Generate at: id.atlassian.com → Security → API tokens |
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
EOL & Release Report — YYYY-MM-DD
```

The page contains a summary panel at the top (green if all clear, yellow if issues found) followed by a table covering each tracked application with its latest release, EOL date, days remaining, and any warnings.

If `CONFLUENCE_PARENT_PAGE_ID` is set, all daily pages are nested under that parent page, keeping your space organised over time.

---

## Cron Setup

Edit your crontab with `crontab -e`:

```bash
# Run every day at 8:00 AM
0 8 * * * cd /path/to/eol-tracker && .venv/bin/python checker.py
```

Using `.venv/bin/python` ensures cron uses the correct interpreter and installed dependencies.

---

## Adding a New Application

Open `applications.yaml` and add a new entry:

```yaml
  - name: My App
    github_repo: owner/repo
    eol_name: my-app          # product slug on endoflife.date (if listed)
    tracked_cycle: "3.2"      # major.minor cycle for EOL lookups
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