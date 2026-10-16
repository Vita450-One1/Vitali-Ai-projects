"""Trip Planner Agent - a web chat page for the agent in agent.py.

Run:  .venv\\Scripts\\python.exe web_app.py
Then open http://127.0.0.1:7860 in your browser.
"""

import queue
import threading

import gradio as gr
from google.genai import types

from agent import ask_agent  # the same agent you use in the terminal


def chat(message: str, history: list, conversation: list):
    """Called by Gradio each time the user sends a message.

    `history` is what the page shows; `conversation` is the agent's own memory
    of this chat (kept separately for every browser tab).
    """
    start = len(conversation)
    conversation.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))

    # Run the agent in the background so the page can show its steps live.
    steps = queue.Queue()
    outcome = {}

    def run():
        try:
            outcome["answer"] = ask_agent(conversation, log=lambda line: steps.put(line.strip()))
        except Exception as e:
            outcome["error"] = str(e)
        steps.put(None)  # signal: finished

    threading.Thread(target=run).start()

    # While the agent works, show its tool calls in a collapsible "Working..." box.
    log_lines = []
    while (line := steps.get()) is not None:
        log_lines.append(line)
        yield [
            gr.ChatMessage(
                content="\n".join(log_lines),
                metadata={"title": "🔧 Working...", "status": "pending"},
            )
        ], conversation

    tools_used = sum(line.startswith("[tool]") for line in log_lines)
    working = gr.ChatMessage(
        content="\n".join(log_lines) or "No tools needed.",
        metadata={"title": f"🔧 Used {tools_used} tool{'s' if tools_used != 1 else ''}"},
    )
    if "error" in outcome:
        del conversation[start:]  # forget the failed question so it can be asked again
        yield [working, gr.ChatMessage(content=f"⚠️ {outcome['error']}")], conversation
    else:
        yield [working, gr.ChatMessage(content=outcome["answer"])], conversation


conversation_state = gr.State([])

demo = gr.ChatInterface(
    fn=chat,
    additional_inputs=[conversation_state],
    additional_outputs=[conversation_state],
    additional_inputs_accordion=gr.Accordion(visible=False),  # nothing for users to set
    title="✈️ Trip Planner Agent",
    description="Ask me to plan a trip. I check live weather, exchange rates and Wikipedia.",
    examples=[
        ["Plan 3 days in Budapest for 4 people with a $700 budget. Show it in forints too.", []],
        ["What should I pack for Lisbon this week?", []],
        ["I have 500 euros. How much is that in shekels?", []],
    ],
    run_examples_on_click=False,
)

if __name__ == "__main__":
    demo.launch(inbrowser=True)  # opens the page in your browser automatically
