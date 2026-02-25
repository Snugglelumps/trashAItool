from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from commands import cmd_compress, cmd_delete, cmd_exit, cmd_help, cmd_list, cmd_load, cmd_new, cmd_reload

YELLOW = "\033[33m"
RESET = "\033[0m"

TITLE_PROMPT = "Summarize this conversation into a three word title. No punctuation."
INVALID_FILENAME_CHARS = '<>:"/\\|?*'
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}


def sanitize_filename(name: str) -> str:
    for ch in INVALID_FILENAME_CHARS:
        name = name.replace(ch, "")
    name = name.strip()
    if name.upper() in WINDOWS_RESERVED:
        name = f"_{name}"
    return name


def unique_path(base_dir: str, name: str) -> tuple[str, str]:
    """Return (final_name, path) with -2/-3 suffix if needed."""
    base = name
    path = os.path.join(base_dir, f"{base}.json")
    if not os.path.exists(path):
        return base, path

    i = 2
    while True:
        candidate = f"{base}-{i}"
        path = os.path.join(base_dir, f"{candidate}.json")
        if not os.path.exists(path):
            return candidate, path
        i += 1


@dataclass
class AppState:
    client: OpenAI
    session: PromptSession
    history_dir: str

    current_name: str | None = None
    mem: list[dict] = field(default_factory=list)

    history: list[dict] = field(default_factory=list)
    history_by_name: dict[str, dict] = field(default_factory=dict)


class AiCLICompleter(Completer):
    def __init__(self, state: AppState, command_table: list[dict]):
        self.state = state
        self.command_table = command_table

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        lower_text = text.lower()

        if " " not in text:
            for cmd in (entry["command"] for entry in self.command_table):
                if cmd.startswith(lower_text):
                    yield Completion(cmd, start_position=-len(text))

        command_name, separator, remainder = text.partition(" ")
        if separator and command_name.lower() in {"load", "delete"}:
            prefix = remainder
            for n in self.state.history_by_name.keys():
                if n.lower().startswith(prefix.lower()):
                    yield Completion(n, start_position=-len(prefix))


def load_history(state: AppState) -> None:
    state.history.clear()
    state.history_by_name.clear()

    for file in os.listdir(state.history_dir):
        if not file.lower().endswith(".json"):
            continue
        path = os.path.join(state.history_dir, file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if isinstance(entry, dict) and {"name", "created", "conversation"} <= entry.keys():
                state.history.append(entry)
                state.history_by_name[entry["name"]] = entry
        except Exception:
            pass

    print(f"Loaded {len(state.history)} conversations from history.")


def load_conversation(state: AppState, name: str) -> None:
    entry = state.history_by_name.get(name)
    if not entry:
        print("No conversation found with that name.")
        return
    state.mem = entry["conversation"].copy()
    state.current_name = name
    print(f"Loaded conversation: {name}")


def save_conversation(state: AppState, name: str) -> None:
    if not state.mem:
        return

    entry = {
        "name": name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "conversation": state.mem.copy(),
    }

    final_name, path = unique_path(state.history_dir, name)
    entry["name"] = final_name

    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)

    # update in-memory index so tab-complete sees it immediately
    state.history.append(entry)
    state.history_by_name[final_name] = entry
    state.current_name = final_name


def model_reply(state: AppState, messages: list[dict]) -> str:
    resp = state.client.responses.create(model="gpt-5.2", input=messages)
    return resp.output_text.strip()


def generate_title_from_mem(state: AppState) -> str:
    # IMPORTANT: don't mutate the real conversation
    temp = state.mem + [{"role": "user", "content": TITLE_PROMPT}]
    return model_reply(state, temp)


def run_command(state: AppState, command_table: list[dict], line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return False

    parts = normalized.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) == 2 else ""

    cmd = next((c for c in command_table if c["command"] == name), None)
    if not cmd:
        return False

    # command expects arg?
    if cmd.get("takes_arg", False):
        cmd["func"](arg)
        return True

    if arg:
        return False

    cmd["func"]()
    return True


def main():
    base_dir = os.path.join(os.getenv("APPDATA"), "trashAItool")
    history_dir = os.path.join(base_dir, "history")
    os.makedirs(history_dir, exist_ok=True)

    state = AppState(client=OpenAI(), session=PromptSession(), history_dir=history_dir)

    command_table = [
        {"command": "help",   "func": lambda:          cmd_help(command_table),      "description": "Show available commands"},
        {"command": "list",   "func": lambda:          cmd_list(state),              "description": "List saved conversations"},
        {"command": "load",   "func": lambda arg=None: cmd_load(state, arg or "", load_conversation), "description": "Load a saved conversation", "takes_arg": True},
        {"command": "delete", "func": lambda arg=None: cmd_delete(state, arg or ""), "description": "Delete a saved conversation", "takes_arg": True},
        {"command": "compress", "func": lambda:        cmd_compress(state, model_reply), "description": "Compress current conversation into a summary"},
        {"command": "reload", "func": lambda:          cmd_reload(state, load_history), "description": "Reload saved conversations from disk"},
        {"command": "new",    "func": lambda:          cmd_new(state),               "description": "Start a new conversation"},
        {"command": "exit",   "func": lambda:          cmd_exit(state, generate_title_from_mem, sanitize_filename, save_conversation), "description": "Exit the application"},
    ]

    completer = AiCLICompleter(state, command_table)

    print("trashAItool Enabled. CTRL+C to exit.")
    print("Type 'help' for a list of commands.")
    load_history(state)

    while True:
        try:
            user = state.session.prompt("> ", completer=completer)

            if run_command(state, command_table, user):
                continue

        except SystemExit:
            break

        state.mem.append({"role": "user", "content": user})
        reply = model_reply(state, state.mem)
        print(YELLOW + reply + RESET)
        state.mem.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
