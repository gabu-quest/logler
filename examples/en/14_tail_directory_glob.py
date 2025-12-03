"""
Tail multiple logs with glob patterns.

Usage:
    python examples/en/14_tail_directory_glob.py

This tails all November 2025 logs under examples/logs/huge (and any other dirs),
demonstrating wildcard expansion and concurrent follow.
"""

import asyncio
import glob
import os
from logler.log_reader import LogReader

PATTERN = os.path.join("examples", "logs", "**", "2025-11-*.log")


async def tail_file(path):
    def consume():
        reader = LogReader(path)
        print(f"==> tailing {path}")
        for line in reader.tail(num_lines=5, follow=False):
            print(f"{os.path.basename(path)}: {line}")
    await asyncio.to_thread(consume)


async def main():
    files = glob.glob(PATTERN, recursive=True)
    if not files:
        print(f"No files matched {PATTERN}")
        return
    tasks = [tail_file(f) for f in files]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
