"""Background loop: sync every few minutes while the pasted Graph token is valid.

  python -m src.worker          # run continuously
  python -m src.worker --once   # one sync, then exit

When the token expires (about an hour), the worker pauses and waits. Paste a new token in the
dashboard (or run `python -m src.graph_token`) and it carries on, catching up on anything missed.
Logs contain message IDs and labels only, never email text or the token.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from . import graph_token, store
from .config import get_config
from .graph_token import TokenExpired
from .llm import ClaudeClassifier
from .sync import sync_once

log = logging.getLogger("worker")


def maybe_purge(con, cfg) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    if store.get_state(con, "last_purge") != today:
        n = store.purge(con, cfg["worker"].get("retention_days", 90))
        store.set_state(con, "last_purge", today)
        if n:
            log.info("retention: removed %d old records", n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    con = store.connect()
    waiting_for_token = False
    while True:
        get_config.cache_clear()
        cfg = get_config()
        try:
            token = graph_token.get()
            if waiting_for_token:
                log.info("new token found, resuming")
                waiting_for_token = False
            rep = sync_once(con, cfg, token, ClaudeClassifier(cfg))
            if rep.labelled or rep.last_error:
                log.info("sync: %d labelled, %d left for next sync, %d sent to review%s", rep.labelled,
                         rep.remaining, rep.failed, f" (last error: {rep.last_error})" if rep.last_error else "")
            info = graph_token.inspect(token)
            if info.minutes_left is not None and info.minutes_left < 10:
                log.warning("Graph token expires in %.0f minutes; paste a new one soon", info.minutes_left)
            maybe_purge(con, cfg)
        except TokenExpired as e:
            if not waiting_for_token:
                log.warning("%s Waiting for a new token...", e)
                waiting_for_token = True
            if args.once:
                raise SystemExit(str(e))
        except Exception:
            log.exception("sync failed; retrying next cycle")
        if args.once:
            break
        time.sleep(15 if waiting_for_token else cfg["worker"].get("poll_seconds", 120))


if __name__ == "__main__":
    main()
