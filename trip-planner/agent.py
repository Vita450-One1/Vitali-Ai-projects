"""Trip Planner Agent - Step 2: several tools that the agent chains together."""

import ast
import json
import operator
import time

import requests
from google import genai
from google.genai import errors, types

# Tried in order: if the first model is busy, the agent falls back to the next.
MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

SYSTEM_PROMPT = """You are a friendly travel assistant who plans trips.
Use your tools for facts instead of guessing:
- weather for anything that depends on the weather
- currency conversion for prices and budgets in another currency
- Wikipedia to look up attractions and neighborhoods
- the calculator for ANY arithmetic, such as splitting a budget
Keep answers practical, and show the budget per person and per day."""


# --- PART 1: the tools (normal Python functions) -------------------------

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


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money using today's exchange rates from Frankfurter (free, no key)."""
    data = requests.get(
        "https://api.frankfurter.dev/v1/latest",
        params={"amount": amount, "base": from_currency.upper(), "symbols": to_currency.upper()},
        timeout=30,
    )
    if data.status_code != 200:
        return {"error": f"Can't convert {from_currency} to {to_currency}"}
    data = data.json()
    return {
        "amount": amount,
        "from": data["base"],
        "converted": data["rates"][to_currency.upper()],
        "to": to_currency.upper(),
        "rate_date": data["date"],
    }


WIKIPEDIA_HEADERS = {"User-Agent": "TripPlannerLearningAgent/1.0"}  # Wikipedia asks for this


def search_wikipedia(query: str) -> dict:
    """Search Wikipedia and return short summaries of the top 3 articles."""
    results = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": query,
                "srlimit": 3, "format": "json"},
        headers=WIKIPEDIA_HEADERS,
        timeout=30,
    ).json()["query"]["search"]

    articles = []
    for result in results:
        summary = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + result["title"].replace(" ", "_"),
            headers=WIKIPEDIA_HEADERS,
            timeout=30,
        ).json()
        articles.append({"title": result["title"], "summary": summary.get("extract", "")})
    return {"query": query, "articles": articles}


OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
}


def calculate(expression: str) -> dict:
    """Safely calculate a math expression like '700 / 4 / 3'."""
    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](evaluate(node.operand))
        raise ValueError("Only numbers and + - * / ** are allowed")

    result = evaluate(ast.parse(expression, mode="eval").body)
    return {"expression": expression, "result": round(result, 2)}


# --- PART 2: the tool descriptions (the AI only sees these, not the code) --

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

currency_tool = types.FunctionDeclaration(
    name="convert_currency",
    description="Convert an amount of money between currencies using today's exchange rate. "
    "Use 3-letter currency codes like USD, EUR, ILS, HUF.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "amount": {"type": "number"},
            "from_currency": {"type": "string", "description": "e.g. 'USD'"},
            "to_currency": {"type": "string", "description": "e.g. 'EUR'"},
        },
        "required": ["amount", "from_currency", "to_currency"],
    },
)

wikipedia_tool = types.FunctionDeclaration(
    name="search_wikipedia",
    description="Search Wikipedia for facts about places: attractions, neighborhoods, "
    "museums, history. Returns short summaries of the top 3 articles.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "e.g. 'Budapest thermal baths'"},
        },
        "required": ["query"],
    },
)

calculator_tool = types.FunctionDeclaration(
    name="calculate",
    description="Calculate a math expression. Use it for every calculation, "
    "such as splitting a budget per person and per day.",
    parameters_json_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "e.g. '700 / 4 / 3'"},
        },
        "required": ["expression"],
    },
)

TOOL_FUNCTIONS = {
    "get_weather": get_weather,
    "convert_currency": convert_currency,
    "search_wikipedia": search_wikipedia,
    "calculate": calculate,
}


# --- PART 3: the agent loop ----------------------------------------------

client = genai.Client()  # reads your key from the GEMINI_API_KEY environment variable

config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=[
        weather_tool, currency_tool, wikipedia_tool, calculator_tool,
    ])],
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
