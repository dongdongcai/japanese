import html
import json
import os
import sys
from typing import Any, Dict, List

import requests


OPENAI_API_URL = "https://api.openai.com/v1/responses"
ANKI_CONNECT_URL = "http://localhost:8765"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")
DEFAULT_DECK = os.getenv("ANKI_DECK", "Japanese Reading")
DEFAULT_NOTE_TYPE = os.getenv("ANKI_NOTE_TYPE", "Basic")
REQUEST_TIMEOUT = 60


def format_html(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def extract_text_from_response(response_data: Dict[str, Any]) -> str:
    if response_data.get("output_text"):
        return response_data["output_text"]

    texts: List[str] = []
    for item in response_data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(content["text"])

    return "\n".join(texts).strip()


def generate_content(japanese_sentence: str) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

    schema = {
        "type": "object",
        "properties": {
            "rewrites": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 2,
            },
            "scenarios_zh": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 2,
            },
            "explanation_zh": {"type": "string"},
        },
        "required": ["rewrites", "scenarios_zh", "explanation_zh"],
        "additionalProperties": False,
    }

    payload = {
        "model": DEFAULT_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a Japanese language assistant. "
                    "Return valid JSON only. "
                    "Given one Japanese sentence, generate exactly:"
                    " 1) 2 natural Japanese rewrites,"
                    " 2) 2 realistic usage scenarios in Chinese,"
                    " 3) 1 short explanation in Chinese about nuance and usage. "
                    "Keep the rewrites natural, concise, and realistic."
                ),
            },
            {
                "role": "user",
                "content": f"Japanese sentence: {japanese_sentence}",
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "japanese_anki_content",
                "schema": schema,
                "strict": True,
            }
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            OPENAI_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to connect to OpenAI API: {exc}") from exc

    try:
        response_data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"OpenAI API returned a non-JSON response (status {response.status_code})."
        ) from exc

    if response.status_code != 200:
        error_message = (
            response_data.get("error", {}).get("message")
            or response_data.get("message")
            or "Unknown OpenAI API error."
        )
        raise RuntimeError(f"OpenAI API error: {error_message}")

    output_text = extract_text_from_response(response_data)
    if not output_text:
        raise RuntimeError("OpenAI API returned an empty response.")

    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse structured JSON from OpenAI response.") from exc

    rewrites = result.get("rewrites")
    scenarios_zh = result.get("scenarios_zh")
    explanation_zh = result.get("explanation_zh")

    if (
        not isinstance(rewrites, list)
        or len(rewrites) != 2
        or not all(isinstance(item, str) and item.strip() for item in rewrites)
    ):
        raise RuntimeError("Invalid rewrites data returned by OpenAI.")

    if (
        not isinstance(scenarios_zh, list)
        or len(scenarios_zh) != 2
        or not all(isinstance(item, str) and item.strip() for item in scenarios_zh)
    ):
        raise RuntimeError("Invalid scenario data returned by OpenAI.")

    if not isinstance(explanation_zh, str) or not explanation_zh.strip():
        raise RuntimeError("Invalid explanation data returned by OpenAI.")

    return {
        "rewrites": [item.strip() for item in rewrites],
        "scenarios_zh": [item.strip() for item in scenarios_zh],
        "explanation_zh": explanation_zh.strip(),
    }


def add_to_anki(notes: List[Dict[str, Any]]) -> List[Any]:
    payload = {
        "action": "addNotes",
        "version": 6,
        "params": {"notes": notes},
    }

    try:
        response = requests.post(
            ANKI_CONNECT_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "Failed to connect to AnkiConnect. Please make sure Anki is open and AnkiConnect is installed."
        ) from exc

    try:
        response_data = response.json()
    except ValueError as exc:
        raise RuntimeError("AnkiConnect returned a non-JSON response.") from exc

    if response.status_code != 200:
        raise RuntimeError(f"AnkiConnect HTTP error: status {response.status_code}")

    if response_data.get("error"):
        raise RuntimeError(f"AnkiConnect error: {response_data['error']}")

    result = response_data.get("result")
    if not isinstance(result, list) or len(result) != len(notes):
        raise RuntimeError("Unexpected response from AnkiConnect when adding notes.")

    return result


def main() -> None:
    try:
        japanese_sentence = input("请输入日语句子: ").strip()
        if not japanese_sentence:
            print("错误：输入不能为空。")
            sys.exit(1)

        generated = generate_content(japanese_sentence)

        rewrites = generated["rewrites"]
        scenarios_zh = generated["scenarios_zh"]
        explanation_zh = generated["explanation_zh"]

        print("\n生成结果：")
        print("改写：")
        print(f"1. {rewrites[0]}")
        print(f"2. {rewrites[1]}")
        print("场景：")
        print(f"1. {scenarios_zh[0]}")
        print(f"2. {scenarios_zh[1]}")
        print(f"说明：{explanation_zh}")

        card_1_front = "<br>".join(
            [
                "使用场景",
                f"1. {format_html(scenarios_zh[0])}",
                f"2. {format_html(scenarios_zh[1])}",
            ]
        )
        card_1_back = "<br>".join(
            [
                "自然表达",
                f"1. {format_html(rewrites[0])}",
                f"2. {format_html(rewrites[1])}",
            ]
        )

        card_2_front = format_html(japanese_sentence)
        card_2_back = "<br><br>".join(
            [
                f"说明：{format_html(explanation_zh)}",
                "<br>".join(
                    [
                        "改写：",
                        f"1. {format_html(rewrites[0])}",
                        f"2. {format_html(rewrites[1])}",
                    ]
                ),
            ]
        )

        notes = [
            {
                "deckName": DEFAULT_DECK,
                "modelName": DEFAULT_NOTE_TYPE,
                "fields": {
                    "Front": card_1_front,
                    "Back": card_1_back,
                },
                "options": {"allowDuplicate": True},
                "tags": ["japanese", "openai", "scenario"],
            },
            {
                "deckName": DEFAULT_DECK,
                "modelName": DEFAULT_NOTE_TYPE,
                "fields": {
                    "Front": card_2_front,
                    "Back": card_2_back,
                },
                "options": {"allowDuplicate": True},
                "tags": ["japanese", "openai", "rewrite"],
            },
        ]

        note_ids = add_to_anki(notes)

        print("\n成功：已添加 2 张 Anki 卡片。")
        print(f"Note IDs: {note_ids[0]}, {note_ids[1]}")

    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(1)
    except Exception as exc:
        print(f"\n错误：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
