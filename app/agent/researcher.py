"""
Research agent — orchestration loop.

Runs a tool-use conversation: the model plans, calls tools, reads results,
and continues until it produces a final answer or hits the turn limit.

Usage:
    # Step-1 loop verification (stubbed tools, test prompt):
    uv run python -m app.agent.researcher --test

    # Full research run (needs USE_STUBS=False in tools.py + server running):
    uv run python -m app.agent.researcher AVGO
"""

import argparse
import asyncio
import logging
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from app.agent.prompts import ANALYST_SYSTEM_PROMPT, STEP1_TEST_PROMPT
from app.agent.tools import TOOLS, execute_tool

load_dotenv()
logger = logging.getLogger(__name__)

AGENT_MODEL = os.environ["LLM_CLAUDE_MODEL"]
MAX_TURNS = int(os.environ["LOOP_MAX_TURNS"])

def _roll_cache_breakpoint(messages: list) -> None:
    """Place a single cache_control breakpoint on the last block of the last
    turn, and strip any stale ones. The cached prefix is tools + system + all
    prior messages, so each turn reads the whole growing history from cache
    (~0.1x) instead of re-billing it at full price."""
    for msg in messages:
        content = msg["content"]
        if isinstance(content, list):
            for block in content:
                # response.content blocks are SDK objects, not dicts — skip them
                if isinstance(block, dict):
                    block.pop("cache_control", None)

    last = messages[-1]["content"]
    if isinstance(last, str):
        # Wrap a bare string turn so we can attach the breakpoint.
        messages[-1]["content"] = last = [{"type": "text", "text": last}]
    if isinstance(last[-1], dict):
        last[-1]["cache_control"] = {"type": "ephemeral"}


async def run_agent(user_task: str, system_prompt: str) -> str:
    client = AsyncAnthropic()
    messages = [{"role": "user", "content": user_task}]

    for turn in range(MAX_TURNS):
        logger.info(f"\n--- turn {turn + 1} ---")
        _roll_cache_breakpoint(messages)
        response = await client.messages.create(
            model=AGENT_MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )
        u = response.usage
        logger.info(
            f"  [tokens] in={u.input_tokens} "
            f"cache_write={u.cache_creation_input_tokens} "
            f"cache_read={u.cache_read_input_tokens} out={u.output_tokens}"
        )

        # Print any thinking-out-loud text the model emits alongside tool calls
        for block in response.content:
            if block.type == "text" and block.text.strip():
                logger.info(f"  [agent] {block.text.strip()}")

        if response.stop_reason != "tool_use":
            final = "".join(
                b.text for b in response.content if b.type == "text"
            )
            logger.info(f"\n[agent finished after {turn + 1} turns]")
            return final

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await execute_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "ERROR: hit MAX_TURNS without finishing."


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="EDGAR research agent")
    parser.add_argument(
        "ticker", nargs="?", help="Ticker to research (omit with --test)"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run the step-1 loop verification against stubbed tools",
    )
    args = parser.parse_args()

    if args.test:
        task = "Run the test task described in your instructions."
        prompt = STEP1_TEST_PROMPT
    elif args.ticker:
        task = f"Run the full research checklist for {args.ticker}."
        prompt = ANALYST_SYSTEM_PROMPT
    else:
        parser.error("provide a ticker, or use --test")

    result = asyncio.run(run_agent(task, prompt))
    logger.info("\n=== RESEARCH MEMO ===\n")
    logger.info(result)


if __name__ == "__main__":
    main()