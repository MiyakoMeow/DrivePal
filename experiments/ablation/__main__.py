"""python -m experiments.ablation 入口."""

import asyncio

from experiments.ablation.cli import main

if __name__ == "__main__":
    asyncio.run(main())
