#!/usr/bin/env python3
"""
Terminal chat client for vLLM-served Qwen3.8-27B on DGX Spark.
Supports thinking mode, reasoning effort, and streaming output.

Usage:
    python chat_terminal.py
    python chat_terminal.py --host 127.0.0.1 --port 8000
    python chat_terminal.py --no-thinking          # disable thinking mode
    python chat_terminal.py --reasoning-effort low  # xhigh/medium/low
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
WHITE = "\033[37m"
BLUE = "\033[34m"

DEFAULT_SYSTEM = "You are Qwen, a helpful AI assistant developed by Alibaba. You are running locally on NVIDIA DGX Spark."
HISTORY_FILE = os.path.expanduser("~/.qwen_chat_history")

THINK_PARAMS = {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "presence_penalty": 0.0}
INSTRUCT_PARAMS = {"temperature": 0.7, "top_p": 0.80, "top_k": 20, "presence_penalty": 1.5}


def stream_chat(base_url, model, messages, thinking=True, reasoning_effort="xhigh",
                max_tokens=8192, preserve_thinking=True):
    """Stream chat with thinking/reasoning support."""
    url = f"{base_url}/chat/completions"

    params = THINK_PARAMS if thinking else INSTRUCT_PARAMS
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "top_k": params["top_k"],
        "presence_penalty": params["presence_penalty"],
        "temperature": params["temperature"],
        "top_p": params["top_p"],
        "extra_body": {
            "chat_template_kwargs": {
                "enable_thinking": thinking,
                "preserve_thinking": preserve_thinking,
            },
        },
    }

    if thinking and reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    reasoning_parts = []
    answer_parts = []
    usage_info = None
    in_thinking = False
    in_answer = False

    with urllib.request.urlopen(req, timeout=600) as resp:
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

            rc = delta.get("reasoning_content") or delta.get("reasoning")
            if rc:
                if not in_thinking:
                    in_thinking = True
                    print(f"\n{DIM}{BLUE}--- thinking ---{RESET}\n{DIM}", end="", flush=True)
                print(rc, end="", flush=True)
                reasoning_parts.append(rc)

            content = delta.get("content", "")
            if content:
                if in_thinking and not in_answer:
                    in_answer = True
                    print(f"{RESET}\n{DIM}--- answer ---{RESET}\n", flush=True)
                elif not in_answer:
                    in_answer = True
                print(content, end="", flush=True)
                answer_parts.append(content)

            if choices[0].get("finish_reason"):
                break

    if in_thinking:
        print(f"{RESET}")
    print()

    full_reply = {
        "reasoning": "".join(reasoning_parts),
        "content": "".join(answer_parts),
    }
    return full_reply, usage_info


def check_server(base_url):
    url = f"{base_url}/models"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, [m["id"] for m in data.get("data", [])]
    except Exception as e:
        return False, str(e)


def print_banner(model_name, base_url, thinking, effort):
    mode = f"thinking ({effort})" if thinking else "instruct (direct)"
    print(f"""
{CYAN}{BOLD}  +==============================================+
  |     Qwen3.8-27B  Terminal Chat  (DGX Spark)  |
  +==============================================+{RESET}
  {DIM}Model:{RESET}  {BOLD}{model_name}{RESET}
  {DIM}API:{RESET}    {base_url}
  {DIM}Mode:{RESET}   {GREEN}{mode}{RESET}
  {DIM}Cmd:{RESET}    {GREEN}/help{RESET} for commands, {GREEN}/quit{RESET} to exit
""")


def print_help():
    print(f"""
{BOLD}Commands:{RESET}
  {GREEN}/help{RESET}              Show this help
  {GREEN}/clear{RESET}             Clear conversation history
  {GREEN}/system <msg>{RESET}      Set system prompt
  {GREEN}/think on|off{RESET}      Toggle thinking mode
  {GREEN}/effort <level>{RESET}    Set reasoning effort: xhigh, medium, low
  {GREEN}/tokens <n>{RESET}        Set max output tokens
  {GREEN}/history{RESET}           Show conversation summary
  {GREEN}/quit{RESET}              Exit
""")


def save_history(messages):
    try:
        safe = [m for m in messages if m["role"] in ("system", "user", "assistant")]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
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
    parser.add_argument("--model", default="Qwen3.8-27B", help="Served model name")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System prompt")
    parser.add_argument("--no-thinking", action="store_true", help="Disable thinking mode")
    parser.add_argument("--reasoning-effort", default="xhigh", choices=["xhigh", "medium", "low"])
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max output tokens")
    parser.add_argument("--no-history", action="store_true", help="Don't save/load history")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/v1"

    ok, info = check_server(base_url)
    if not ok:
        print(f"{RED}Error: Cannot connect to vLLM server at {base_url}{RESET}")
        print(f"  {info}")
        print(f"\n  Start vLLM on spark:")
        print(f"    tmux new -s vllm")
        print(f"    bash ~/Qwen3.8-27B/start_vllm.sh")
        sys.exit(1)

    model_name = args.model
    if isinstance(info, list) and info:
        model_name = info[0]

    thinking = not args.no_thinking
    effort = args.reasoning_effort
    max_tokens = args.max_tokens

    print_banner(model_name, base_url, thinking, effort)

    messages = [{"role": "system", "content": args.system}]

    if not args.no_history:
        prev = load_history()
        user_count = sum(1 for m in prev if m["role"] == "user")
        if user_count:
            print(f"  {DIM}Found {user_count} previous messages. /clear to start fresh.{RESET}\n")

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
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                print(f"{DIM}Bye!{RESET}")
                break
            elif cmd == "/help":
                print_help()
            elif cmd == "/clear":
                messages = [{"role": "system", "content": args.system}]
                if not args.no_history:
                    save_history(messages)
                print(f"{YELLOW}Conversation cleared.{RESET}\n")
            elif cmd == "/system":
                if arg:
                    messages[0]["content"] = arg
                    print(f"{YELLOW}System prompt updated.{RESET}\n")
                else:
                    print(f"  Current: {messages[0]['content']}\n")
            elif cmd == "/think":
                if arg in ("on", "true", "1"):
                    thinking = True
                    print(f"{YELLOW}Thinking mode ON{RESET}\n")
                elif arg in ("off", "false", "0"):
                    thinking = False
                    print(f"{YELLOW}Thinking mode OFF (instruct/direct){RESET}\n")
                else:
                    status = "ON" if thinking else "OFF"
                    print(f"  Thinking is currently {status}\n")
            elif cmd == "/effort":
                if arg in ("xhigh", "medium", "low"):
                    effort = arg
                    print(f"{YELLOW}Reasoning effort: {effort}{RESET}\n")
                else:
                    print(f"  Current effort: {effort} (options: xhigh, medium, low)\n")
            elif cmd == "/tokens":
                try:
                    max_tokens = int(arg)
                    print(f"{YELLOW}Max tokens: {max_tokens}{RESET}\n")
                except ValueError:
                    print(f"{RED}Invalid number{RESET}\n")
            elif cmd == "/history":
                user_count = sum(1 for m in messages if m["role"] == "user")
                total_chars = sum(len(m.get("content", "")) for m in messages)
                mode = "thinking" if thinking else "instruct"
                print(f"  Turns: {user_count} | Chars: {total_chars} | Mode: {mode} | Effort: {effort}\n")
            else:
                print(f"{RED}Unknown command: {cmd}. Type /help{RESET}\n")
            continue

        messages.append({"role": "user", "content": user_input})

        print(f"\n{MAGENTA}{BOLD}Qwen>{RESET} ", end="", flush=True)

        try:
            reply, usage = stream_chat(
                base_url, model_name, messages,
                thinking=thinking,
                reasoning_effort=effort,
                max_tokens=max_tokens,
            )
        except urllib.error.URLError as e:
            print(f"\n{RED}Connection error: {e}{RESET}")
            messages.pop()
            continue
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")
            messages.pop()
            continue

        content = reply["content"]
        if content:
            assistant_msg = {"role": "assistant", "content": content}
            if reply["reasoning"]:
                assistant_msg["reasoning_content"] = reply["reasoning"]
            messages.append(assistant_msg)
        else:
            print(f"{YELLOW}(empty response){RESET}")
            messages.pop()

        if usage:
            pt = usage.get("prompt_tokens", "?")
            ct = usage.get("completion_tokens", "?")
            tt = usage.get("total_tokens", "?")
            print(f"{DIM}  [{pt} in / {ct} out / {tt} total]{RESET}")

        print()

        if not args.no_history:
            save_history(messages)


if __name__ == "__main__":
    main()
