#!/usr/bin/env python3
"""
Terminal chat client for vLLM-served Qwen3.8-27B on DGX Spark.
Provides an interactive multi-turn conversation with streaming output,
similar to a web chat experience.

Usage:
    python chat_terminal.py                          # default: localhost:8000
    python chat_terminal.py --host 127.0.0.1 --port 8000
    python chat_terminal.py --system "You are a helpful assistant."

Requires: openai (pip install openai) or just uses urllib (no deps needed).
"""

import argparse
import json
import sys
import os
import urllib.request
import urllib.error
import readline

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"

DEFAULT_SYSTEM = "You are Qwen, a helpful AI assistant developed by Alibaba. You are running on NVIDIA DGX Spark."
HISTORY_FILE = os.path.expanduser("~/.qwen_chat_history")


def stream_chat(base_url, model, messages, temperature=0.7, max_tokens=4096):
    """Stream chat completion tokens via OpenAI-compatible API using urllib."""
    url = f"{base_url}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    collected = []
    usage_info = None

    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if "usage" in chunk and chunk["usage"] is not None:
                usage_info = chunk["usage"]

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                collected.append(content)
                print(content, end="", flush=True)

            if choices[0].get("finish_reason"):
                break

    print()
    return "".join(collected), usage_info


def check_server(base_url):
    """Check if the vLLM server is reachable."""
    url = f"{base_url}/models"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            return True, models
    except Exception as e:
        return False, str(e)


def print_banner(model_name, base_url):
    print(f"{CYAN}{BOLD}")
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║     Qwen3.8-27B  Terminal Chat  (DGX Spark) ║")
    print("  ╚══════════════════════════════════════════════╝")
    print(f"{RESET}")
    print(f"  {DIM}Model:{RESET}  {BOLD}{model_name}{RESET}")
    print(f"  {DIM}API:{RESET}    {base_url}")
    print(f"  {DIM}Type:{RESET}   {GREEN}/help{RESET} for commands, {GREEN}/quit{RESET} to exit")
    print()


def print_help():
    print(f"""
{BOLD}Commands:{RESET}
  {GREEN}/help{RESET}        Show this help message
  {GREEN}/clear{RESET}       Clear conversation history
  {GREEN}/system <msg>{RESET} Set system prompt
  {GREEN}/temp <value>{RESET}  Set temperature (0.0-2.0)
  {GREEN}/tokens <n>{RESET}    Set max output tokens
  {GREEN}/history{RESET}      Show conversation summary
  {GREEN}/quit{RESET}        Exit the chat
  {GREEN}/exit{RESET}        Exit the chat
""")


def save_history(messages):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Qwen3.8-27B Terminal Chat")
    parser.add_argument("--host", default="127.0.0.1", help="vLLM server host")
    parser.add_argument("--port", type=int, default=8000, help="vLLM server port")
    parser.add_argument("--model", default="Qwen3.8-27B", help="Model name (served name)")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System prompt")
    parser.add_argument("--temperature", type=float, default=0.7, help="Temperature")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max output tokens")
    parser.add_argument("--no-history", action="store_true", help="Don't load/save history")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/v1"

    ok, info = check_server(base_url)
    if not ok:
        print(f"{RED}Error: Cannot connect to vLLM server at {base_url}{RESET}")
        print(f"  {info}")
        print(f"\n  Make sure vLLM is running. On spark:")
        print(f"    tmux new -s vllm")
        print(f"    bash ~/Qwen3.8-27B/start_vllm.sh")
        sys.exit(1)

    model_name = args.model
    if isinstance(info, list) and info:
        model_name = info[0]
        if args.model != info[0]:
            print(f"  {DIM}Auto-detected model:{RESET} {info[0]}")

    print_banner(model_name, base_url)

    messages = [{"role": "system", "content": args.system}]

    if not args.no_history:
        prev = load_history()
        user_msgs = [m for m in prev if m["role"] == "user"]
        if user_msgs:
            print(f"  {DIM}Found {len(user_msgs)} previous messages. Use /clear to start fresh.{RESET}\n")

    temperature = args.temperature
    max_tokens = args.max_tokens
    turn_count = 0

    while True:
        try:
            user_input = input(f"{GREEN}{BOLD}You>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Bye!{RESET}")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                print(f"{DIM}Bye!{RESET}")
                break
            elif cmd == "/help":
                print_help()
            elif cmd == "/clear":
                messages = [{"role": "system", "content": args.system}]
                turn_count = 0
                if not args.no_history:
                    save_history(messages)
                print(f"{YELLOW}Conversation cleared.{RESET}\n")
            elif cmd == "/system":
                if arg:
                    messages[0]["content"] = arg
                    print(f"{YELLOW}System prompt updated.{RESET}\n")
                else:
                    print(f"  Current: {messages[0]['content']}\n")
            elif cmd == "/temp":
                try:
                    temperature = float(arg)
                    print(f"{YELLOW}Temperature set to {temperature}{RESET}\n")
                except ValueError:
                    print(f"{RED}Invalid temperature value{RESET}\n")
            elif cmd == "/tokens":
                try:
                    max_tokens = int(arg)
                    print(f"{YELLOW}Max tokens set to {max_tokens}{RESET}\n")
                except ValueError:
                    print(f"{RED}Invalid token count{RESET}\n")
            elif cmd == "/history":
                user_count = sum(1 for m in messages if m["role"] == "user")
                total_chars = sum(len(m.get("content", "")) for m in messages)
                print(f"  Turns: {user_count}, Total chars: {total_chars}, Temperature: {temperature}\n")
            else:
                print(f"{RED}Unknown command: {cmd}. Type /help for commands.{RESET}\n")
            continue

        messages.append({"role": "user", "content": user_input})
        turn_count += 1

        print(f"\n{MAGENTA}{BOLD}Qwen>{RESET} ", end="", flush=True)

        try:
            reply, usage = stream_chat(base_url, model_name, messages, temperature, max_tokens)
        except urllib.error.URLError as e:
            print(f"\n{RED}Connection error: {e}{RESET}")
            messages.pop()
            continue
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")
            messages.pop()
            continue

        if reply:
            messages.append({"role": "assistant", "content": reply})
        else:
            print(f"{YELLOW}(empty response){RESET}")
            messages.pop()

        if usage:
            prompt_tokens = usage.get("prompt_tokens", "?")
            completion_tokens = usage.get("completion_tokens", "?")
            total_tokens = usage.get("total_tokens", "?")
            print(f"{DIM}  [{prompt_tokens} in / {completion_tokens} out / {total_tokens} total]{RESET}")

        print()

        if not args.no_history:
            save_history(messages)


if __name__ == "__main__":
    main()
