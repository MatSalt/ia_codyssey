"""Private per-operation input files: consumers use precisely the verified bytes."""
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
import tempfile


@asynccontextmanager
async def input_file(data):
    with tempfile.TemporaryDirectory(prefix='mori-input-') as directory:
        path = Path(directory) / 'input'
        # One bounded local write; avoid sharing a canonical R2 cache filename.
        # Await to_thread to completion on cancellation before deleting its directory.
        task = asyncio.create_task(asyncio.to_thread(path.write_bytes, data))
        try:
            await asyncio.shield(task)
            yield path
        finally:
            if not task.done():
                await task
