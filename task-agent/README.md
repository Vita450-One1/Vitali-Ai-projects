# My First AI Agent: To-Do Assistant

A chat assistant that manages your to-do list. You talk to it in plain English and
Claude decides which **tools** (Python functions) to call.

```
You: remind me to call mom tomorrow and buy milk
  [tool] add_task({"title": "Call mom", "due_date": "2026-10-15"})
  [tool] add_task({"title": "Buy milk"})
Agent: Added both tasks.
You: done with the milk
  [tool] list_tasks({})
  [tool] complete_task({"task_id": 2})
Agent: Marked "Buy milk" as done.
```

## What makes this an "agent"?

A plain chatbot only talks. An agent can **act**, and runs in a loop:

1. Send the conversation and a list of tools to the model.
2. The model either answers, or asks to call one or more tools.
3. Your code runs those tools and sends the results back.
4. Repeat until the model answers without asking for a tool.

All of that is in `run_agent_turn()` in `agent.py`, in about 30 lines. Note
that the model decides *on its own* to call `list_tasks` first to look up an ID.
That decision-making is what makes it an agent.

## Run it

```bash
cd task-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # from https://platform.claude.com
python agent.py
```

Tasks are saved in `task-agent/tasks.json`.

## How to learn from it

1. **Read `agent.py` top to bottom.** It has three parts: the tools, the tool
   descriptions (`TOOLS`), and the loop.
2. **Watch the `[tool]` lines.** They show you what the model decided to do.
3. **Break things on purpose.** Remove a tool description or make it vague and
   see how the behavior changes. Most agent quality comes from clear tool
   descriptions and the system prompt.

## Next steps (in rising difficulty)

1. Add an `edit_task` tool (rename it or change the due date).
2. Add a `priority` field and let the agent sort by it.
3. Ask for confirmation in the terminal before `delete_task` runs (a "human in the loop").
4. Add the built-in web search tool so it can research tasks ("find a gift idea for mom").
5. Move from the hand-written loop to the SDK's **Tool Runner**
   (`client.beta.messages.tool_runner`), which runs the loop for you.
6. Build your second agent: an **email triage agent** (read your inbox, summarize,
   draft replies), or a **personal finance agent** that reads a bank-export CSV
   and answers "how much did I spend on food last month?"
