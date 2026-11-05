name: fetch-market-data

on:
  schedule:
    - cron: "15 21 * * 0-4"
    - cron: "5 23 * * 0-4"
    - cron: "5 6 * * 1-5"
    - cron: "5 11 * * 1-5"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: data-push
  cancel-in-progress: false

jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install yfinance pandas
      - run: python fetch_data.py
      - name: Commit data
        run: |
          git config user.name "data-bot"
          git config user.email "data-bot@users.noreply.github.com"
          git add data
          git commit -m "data $(date -u +%F_%H%M)" || echo "no changes"
          git pull --rebase || true
          git push
