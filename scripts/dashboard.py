"""P7-12 · Open the presentation dashboard in the browser.

    python scripts/dashboard.py
    python scripts/dashboard.py --port 8050 --no-browser

Four views: **Run** (replay a test episode block by block), **Compare** (the
test-split results), **Live** (the DEX deployed on preprod) and **How it works**.
Localhost only. Run and Compare work offline; Live needs ``BLOCKFROST_PROJECT_ID``.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from batcher.dashboard.data import EVALUATION, EpisodeLibrary, LiveSource, compare_payload
from batcher.dashboard.server import DashboardProvider, serve

REPO = Path(__file__).resolve().parents[1]


def find_dataset() -> Path | None:
    found = sorted((REPO / "data" / "processed").glob("d1_blocks_*.parquet"))
    return found[-1] if found else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument(
        "--models", type=Path, default=REPO / "experiments/phase3-forecaster/models"
    )
    args = parser.parse_args(argv)

    library = EpisodeLibrary(args.data or find_dataset(), args.models)
    library.start()
    provider = DashboardProvider(library, LiveSource(), lambda: compare_payload(EVALUATION))
    server = serve(provider, "127.0.0.1", args.port)

    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Dashboard running at {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
