import asyncio
import aiohttp
import sys
from pathlib import Path

# Add project root to path (one level up from scratch is friendly-salk)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs import github

async def test_async_helpers():
    print("Testing Jitter...")
    await github.apply_jitter(base_delay=0.1, max_delay=0.2, task_index=0)
    await github.apply_jitter(base_delay=0.1, max_delay=0.2, task_index=1)
    print("Jitter passed!")

    print("Testing aiohttp request helper...")
    settings = {
        "github_token": "mock-token",
        "request_timeout_seconds": 10
    }
    
    async with aiohttp.ClientSession() as session:
        # Request root of github API
        status, body = await github.request("GET", "/", settings, session=session)
        print(f"Request returned status: {status}")
        assert status in (200, 401), f"Unexpected status code {status}"
        print("Async helper requests passed!")

def main():
    asyncio.run(test_async_helpers())

if __name__ == "__main__":
    main()
