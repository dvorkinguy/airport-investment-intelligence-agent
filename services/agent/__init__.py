"""Airport Investment Intelligence Agent - backend package.

Import path is ``agent`` (see pyproject ``tool.hatch.build.targets.wheel.sources``).
"""

import asyncio
import sys

__version__ = "0.1.0"


def configure_event_loop() -> None:
    """Select an event loop psycopg can actually use.

    Windows defaults to ``ProactorEventLoop``, which psycopg's async driver
    refuses outright - every database connection times out with a pool error
    that never names the real cause. Must be called before the loop is created,
    which is why it lives in an entry point rather than in ``main``. No-op
    everywhere except Windows; Cloud Run is unaffected.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
