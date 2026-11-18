"""Convert MinerU HTML tables into grids and plain text after a run."""
import json
from pathlib import Path

from bs4 import BeautifulSoup

p = Path(__file__).resolve().parent.parent / "data/benchmark/results_mineru.jsonl"
rows = []
for line in p.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    text = r.get("markdown", "") or r.get("text", "")
    if "<table" in text:
        soup = BeautifulSoup(text, "lxml")
        grids = []
        for tab in soup.find_all("table"):
            grid = []
            for tr in tab.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if cells:
                    grid.append(cells)
            if len(grid) >= 2:
                grids.append(grid)
        r["tables"] = grids
        r["text"] = soup.get_text("\n", strip=True)
        r["markdown"] = text
    # run_engine.py now measures the process tree; do not add a manual offset.
    r["rss_note"] = "parent + child process peak measured by run_engine.py"
    rows.append(r)
p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
print("postprocessed", len(rows), "rows; tables", sum(len(r.get("tables", [])) for r in rows))
