"""Trip Planner Agent - Step 1: the agent loop with one tool (weather)."""

import json
import time

import requests
from google import genai
from google.genai import errors, types

# Tried in order: if the first model is busy, the agent falls back to the next.
MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

SYSTEM_PROMPT = """You are a friendly travel assistant.
Use the get_weather tool whenever the weather matters to the answer.
Keep answers short and practical."""


# --- PART 1: the tool (a normal Python function) -------------------------

def get_weather(city: str) -> dict:
    """Get the 7-day weather forecast for a city from Open-Meteo (free, no key)."""
    places = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=30,
    ).json()
    if not places.get("results"):
        return {"error": f"City '{city}' not found"}
    place = places["results"][0]

    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
        },
        timeout=30,
    ).json()["daily"]

    return {
        "city": f"{place['name']}, {place.get('country', '')}",
        "days": [
            {"date": d, "max_c": hi, "min_c": lo, "rain_chance_pct": rain}
            for d, hi, lo, rain in zip(
                forecast["time"],
                forecast["temperature_2m_max"],
                forecast["temperature_2m_min"],
                forecast["precipitation_probability_max"],
            )
        ],
    }


# --- PART 2: the tool description (the AI only sees this, not the code) --

weather_tool = types.FunctionDeclaration(
    name="get_weather",
    description="Get the weather forecast for the next 7 days in a city.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. 'Lisbon'"},
        },
        "required": ["city"],
    },
)

TOOL_FUNCTIONS = {"get_weather": get_weather}


# --- PART 3: the agent loop ----------------------------------------------

client = genai.Client()  # reads your key from the GEMINI_API_KEY environment variable

config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[weather_tool])],
    # We run the tools ourselves, so you can see the loop happen.
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def call_model(conversation: list):
    """Send the conversation to Gemini, retrying and falling back when it's busy."""
    for attempt in range(3):
        for model in MODELS:
            try:
                return client.models.generate_content(
                    model=model, contents=conversation, config=config
                )
            except errors.APIError as e:
                # 503 = overloaded, 429 = free-tier limit hit. Anything else is a real error.
                if e.code not in (429, 503):
                    raise
                print(f"   [busy] {model} returned {e.code}, trying the next option...")
        wait = 5 * (attempt + 1)
        print(f"   [wait] all models busy, retrying in {wait} seconds...")
        time.sleep(wait)
    raise RuntimeError("Gemini is busy right now. Please try again in a few minutes.")


def ask_agent(conversation: list) -> str:
    while True:
        # 1. Send the whole conversation to the AI
        response = call_model(conversation)
        # Remember what the AI said (including any tool requests)
        conversation.append(response.candidates[0].content)

        # 2. No tool requests? Then this is the final answer.
        if not response.function_calls:
            return response.text

        # 3. Run each tool the AI asked for and send back the results
        results = []
        for call in response.function_calls:
            print(f"   [tool] {call.name}({json.dumps(call.args)})")
            try:
                output = TOOL_FUNCTIONS[call.name](**call.args)
            except Exception as e:
                output = {"error": str(e)}
            results.append(types.Part.from_function_response(name=call.name, response=output))
        conversation.append(types.Content(role="user", parts=results))
        # ...and loop back to step 1


def main() -> None:
    print("Trip planner ready. Type 'quit' to exit.\n")
    conversation = []
    while True:
        question = input("You: ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        if not question:
            continue
        start = len(conversation)
        conversation.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))
        try:
            print(f"Agent: {ask_agent(conversation)}\n")
        except Exception as e:
            print(f"Agent error: {e}\n")
            del conversation[start:]  # forget the failed question so you can ask again


if __name__ == "__main__":
    main()
