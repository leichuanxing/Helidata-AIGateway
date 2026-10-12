"""Best-effort shutdown of every worker and connection pool."""
import asyncio
import logging

logger = logging.getLogger('app.lifecycle')


async def shutdown(workers, closers):
    for worker in workers:
        worker.cancel()
    results = await asyncio.gather(*workers, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            # Exceptions may contain credentials or upstream response bodies.
            logger.error('Background worker failed (%s)', type(result).__name__)
    for closer in closers:
        try:
            await closer()
        except Exception as error:
            logger.error('Resource shutdown failed (%s)', type(error).__name__)
