"""Run the service:  uv run python -m agent

This is the supported entry point rather than ``uvicorn agent.main:app``, because
of how the event loop has to be chosen on Windows - see below and
``agent.configure_event_loop``. Host and port come from the environment.
"""

from __future__ import annotations

import asyncio
import os
import sys

from agent import configure_event_loop


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    if sys.platform != "win32":
        # Linux/Cloud Run: let uvicorn pick its best loop (uvloop when present).
        uvicorn.run("agent.main:app", host=host, port=port, log_config=None,
                    access_log=False)
        return

    # Windows: uvicorn hands asyncio an explicit ProactorEventLoop factory, which
    # psycopg's async driver refuses - every database connection then times out
    # with a pool error that never names the cause. `loop="none"` makes uvicorn
    # leave the loop alone so the selector policy set below is the one that runs.
    # (`uvicorn --reload` also works here: its subprocess supervisor selects a
    # SelectorEventLoop for the same reason.)
    configure_event_loop()
    config = uvicorn.Config(
        "agent.main:app", host=host, port=port, loop="none",
        log_config=None, access_log=False,
    )
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
