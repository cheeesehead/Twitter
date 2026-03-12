import asyncio
import sys


def main():
    test_mode = "--test-mode" in sys.argv

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from bot.main import run
    asyncio.run(run(test_mode=test_mode))


if __name__ == "__main__":
    main()
