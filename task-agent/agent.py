"""My first AI agent: a personal to-do assistant.

You chat with it in plain English ("remind me to call mom tomorrow",
"what's left for today?", "I finished the gym task"), and Claude decides
which tools to call to read and change your task list.

The whole agent is the loop in `run_agent_turn`:
    1. send the conversation + tool definitions to Claude
    2. if Claude asks to use tools, run them and send back the results
    3. repeat until Claude answers without asking for a tool
"""

import json
from datetime import date
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
TASKS_FILE = Path(__file__).parent / "tasks.json"

SYSTEM_PROMPT = f"""You are a friendly personal to-do assistant.
Today's date is {date.today().isoformat()}.
Use the tools to read and change the user's task list - never invent tasks
or IDs. Before completing or deleting a task, look it up with list_tasks if
you don't already know its ID. Keep replies short."""


# ---------------------------------------------------------------------------
# Tools: plain Python functions that work on a JSON file
# ---------------------------------------------------------------------------

def load_tasks() -> list[dict]:
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text())


def save_tasks(tasks: list[dict]) -> None:
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


def add_task(title: str, due_date: str | None = None) -> str:
    tasks = load_tasks()
    next_id = max((t["id"] for t in tasks), default=0) + 1
    task = {"id": next_id, "title": title, "due_date": due_date, "done": False}
    tasks.append(task)
    save_tasks(tasks)
    return json.dumps(task)


def list_tasks(include_done: bool = False) -> str:
    tasks = load_tasks()
    if not include_done:
        tasks = [t for t in tasks if not t["done"]]
    return json.dumps(tasks) if tasks else "No tasks found."


def complete_task(task_id: int) -> str:
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["done"] = True
            save_tasks(tasks)
            return json.dumps(task)
    raise ValueError(f"No task with id {task_id}")


def delete_task(task_id: int) -> str:
    tasks = load_tasks()
    remaining = [t for t in tasks if t["id"] != task_id]
    if len(remaining) == len(tasks):
        raise ValueError(f"No task with id {task_id}")
    save_tasks(remaining)
    return f"Deleted task {task_id}"


TOOL_FUNCTIONS = {
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "delete_task": delete_task,
}

# Claude only sees these descriptions - they are how it decides what to call.
TOOLS = [
    {
        "name": "add_task",
        "description": "Add a new task to the user's to-do list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task description"},
                "due_date": {
                    "type": "string",
                    "description": "Optional due date in YYYY-MM-DD format",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List the user's tasks with their IDs, due dates and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_done": {
                    "type": "boolean",
                    "description": "Also include completed tasks (default false)",
                },
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as done by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Permanently remove a task by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


def run_tool(name: str, tool_input: dict) -> dict:
    """Run one tool and wrap the outcome as a tool_result payload."""
    try:
        return {"content": TOOL_FUNCTIONS[name](**tool_input)}
    except Exception as e:  # report errors to Claude so it can recover
        return {"content": f"Error: {e}", "is_error": True}


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def run_agent_turn(messages: list) -> str:
    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": "medium"},
            # If a safety classifier declines, retry on Anthropic's
            # recommended fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if response.stop_reason == "refusal":
            return "Sorry, I can't help with that request."

        # Keep Claude's full reply (including tool calls) in the history.
        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            return "".join(b.text for b in response.content if b.type == "text")

        # Run every requested tool and send all results back in one message.
        results = []
        for call in tool_calls:
            print(f"  [tool] {call.name}({json.dumps(call.input)})")
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, **run_tool(call.name, call.input)}
            )
        messages.append({"role": "user", "content": results})


def main() -> None:
    print("To-do agent ready. Type 'quit' to exit.\n")
    messages: list = []
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        if not user_input:
            continue
        messages.append({"role": "user", "content": user_input})
        print(f"Agent: {run_agent_turn(messages)}\n")


if __name__ == "__main__":
    main()
