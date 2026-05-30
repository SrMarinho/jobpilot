import asyncio


def run_async(coro) -> object:
    """Run an async coroutine synchronously.

    Uses ``asyncio.run()`` under the hood.  Having a single function means we
    only ever touch one call-site if the event-loop policy needs to change
    (e.g. switching to a persistent loop, setting a custom executor, etc.).
    """
    return asyncio.run(coro)
