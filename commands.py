from datetime import datetime
import os
from typing import Any, Callable


def cmd_list(state: Any) -> None:
    print("Saved Conversations:")
    for entry in state.history:
        print(f"{entry['name']} ({entry['created']})")


def cmd_new(state: Any) -> None:
    state.mem.clear()
    state.current_name = None
    print("Started a new conversation.")


def cmd_exit(
    state: Any,
    generate_title_from_mem: Callable[[Any], str],
    sanitize_filename: Callable[[str], str],
    save_conversation: Callable[[Any, str], None],
) -> None:
    if not state.mem:
        raise SystemExit

    if state.current_name:
        save_conversation(state, state.current_name)
        print(f"Saved as: {state.current_name}")
        raise SystemExit

    title = generate_title_from_mem(state)
    print(title)

    name = sanitize_filename(title) or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    save_conversation(state, name)

    print(f"Saved as: {state.current_name}")
    raise SystemExit


def cmd_load(state: Any, arg: str, load_conversation: Callable[[Any, str], None]) -> None:
    if not arg:
        print("Usage: load <name>")
        return
    load_conversation(state, arg)


def cmd_delete(state: Any, arg: str) -> None:
    if not arg:
        print("Usage: delete <name>")
        return

    entry = state.history_by_name.get(arg)
    if not entry:
        print("No conversation found with that name.")
        return

    path = os.path.join(state.history_dir, f"{arg}.json")
    if not os.path.exists(path):
        print("Conversation file not found on disk.")
        return

    os.remove(path)
    state.history = [item for item in state.history if item["name"] != arg]
    state.history_by_name.pop(arg, None)

    if state.current_name == arg:
        state.current_name = None

    print(f"Deleted conversation: {arg}")


def cmd_help(command_table: list[dict]) -> None:
    print("Commands:")
    for command in command_table:
        print(f"  {command['command']:<16} {command['description']}")


def cmd_reload(state: Any, load_history: Callable[[Any], None]) -> None:
    load_history(state)


def cmd_compress(state: Any, model_reply: Callable[[Any, list[dict]], str]) -> None:
    if not state.mem:
        print("Nothing to compress.")
        return

    state.mem.append(
        {
            "role": "user",
            "content": (
                "Take all conversation context so far and condense it into a comprehensive summary "
                "that preserves key facts, decisions, constraints, and open tasks."
            ),
        }
    )

    summary = model_reply(state, state.mem)
    state.mem = [{"role": "assistant", "content": summary}]
    print("Conversation compressed.")
