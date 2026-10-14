"""Text and client function-tools bridge for OpenCode's Chat Completions API."""
import json
import secrets
from core import GatewayError

# ponytail: bounded, process-local reasoning continuity; new chats after gateway restart.
REASONING = {}


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict) or part.get("type") not in {"input_text", "output_text", "text"}:
                raise GatewayError("This model's test route currently accepts text only", 422)
            parts.append(part.get("text", ""))
        return "\n".join(parts)
    raise GatewayError("Invalid text content", 422)


def prepare_chat(payload):
    messages = []
    if payload.get("instructions"):
        messages.append({"role": "system", "content": payload["instructions"]})
    for item in payload["input"]:
        kind = item.get("type", "message")
        if kind == "reasoning":
            continue
        if kind == "message":
            role = item["role"]
            if role == "developer":
                role = "system"
            if role not in {"system", "user", "assistant"}:
                raise GatewayError("Unsupported message role", 422)
            messages.append({"role": role, "content": text_content(item["content"])})
        elif kind == "function_call":
            call = {"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}}
            if messages and messages[-1]["role"] == "assistant":
                messages[-1].setdefault("tool_calls", []).append(call)
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            if item["call_id"] in REASONING:
                messages[-1]["reasoning_content"] = REASONING[item["call_id"]]
        elif kind == "function_call_output":
            output = item["output"]
            messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": output if isinstance(output, str) else json.dumps(output)})
        else:
            raise GatewayError("Unsupported Chat Completions history item", 422)
    outgoing = {"model": payload["model"], "messages": messages, "stream": False,
                "max_tokens": payload.get("max_output_tokens", 4096)}
    tools = [{"type": "function", "function": {key: value for key, value in tool.items() if key != "type"}} for tool in payload.get("tools", [])]
    if tools:
        outgoing["tools"] = tools
    if "tool_choice" in payload:
        choice = payload["tool_choice"]
        outgoing["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}} if isinstance(choice, dict) else choice
    return outgoing


def response_events(response, names):
    choices = response.get("choices", [])
    if len(choices) != 1 or choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
        raise GatewayError("Chat provider did not complete its response", 502)
    message = choices[0].get("message", {})
    output = []
    content = message.get("content")
    if content:
        if not isinstance(content, str):
            raise GatewayError("Chat provider returned unsupported output", 502)
        output.append({"type": "message", "id": "msg_" + secrets.token_hex(12), "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": content, "annotations": []}]})
    reasoning = message.get("reasoning_content")
    for call in message.get("tool_calls", []):
        if call.get("type") != "function" or not isinstance(call.get("id"), str):
            raise GatewayError("Chat provider returned invalid function output", 502)
        item = {"type": "function_call", "id": "fc_" + secrets.token_hex(12), "call_id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]}
        if not isinstance(item["arguments"], str):
            raise GatewayError("Chat provider returned invalid function arguments", 502)
        output.append(item)
        if isinstance(reasoning, str):
            REASONING[call["id"]] = reasoning
            while len(REASONING) > 256:
                REASONING.pop(next(iter(REASONING)))
    if not output:
        raise GatewayError("Chat provider returned empty output", 502)
    response_id = "resp_chat_bridge_" + secrets.token_hex(12)
    events = [{"type": "response.created", "response": {"id": response_id, "status": "in_progress", "output": []}}]
    for index, item in enumerate(output):
        initial = dict(item)
        if item["type"] == "function_call":
            initial["arguments"] = ""
        else:
            initial["content"] = []
        events.append({"type": "response.output_item.added", "output_index": index, "item": initial})
        if item["type"] == "function_call":
            events.append({"type": "response.function_call_arguments.delta", "output_index": index, "item_id": item["id"], "delta": item["arguments"]})
        else:
            events.append({"type": "response.output_text.delta", "output_index": index, "content_index": 0, "item_id": item["id"], "delta": item["content"][0]["text"]})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    usage = response.get("usage", {})
    events.append({"type": "response.completed", "response": {"id": response_id, "status": "completed", "output": output, "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0), "total_tokens": usage.get("total_tokens", 0)}}})
    for event in events:
        for translated in names.response_events(event):
            yield ("data: " + json.dumps(translated) + "\n\n").encode(), translated
