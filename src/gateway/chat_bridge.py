"""Text, inline images and client function-tools bridge for Chat Completions."""
import json
import secrets
from core import GatewayError, validate_image

# ponytail: bounded, process-local reasoning continuity; new chats after gateway restart.
REASONING = {}


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'input_image':
                validate_image(part)
                image = {'url': part['image_url']}
                if 'detail' in part:
                    image['detail'] = 'high' if part['detail'] == 'original' else part['detail']
                parts.append({'type': 'image_url', 'image_url': image})
            elif isinstance(part, dict) and part.get('type') in {'input_text', 'output_text', 'text'} and isinstance(part.get('text'), str):
                parts.append({'type': 'text', 'text': part['text']})
            else:
                raise GatewayError('Unsupported Chat Completions content', 422)
        if any(part['type'] == 'image_url' for part in parts):
            return parts
        return '\n'.join(part['text'] for part in parts)
    raise GatewayError("Invalid text content", 422)


def prepare_chat(payload, *, stream=False):
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
    outgoing = {"model": payload["model"], "messages": messages, "stream": stream}
    if stream:
        outgoing['stream_options'] = {'include_usage': True}
    if payload.get('service_tier'):
        outgoing['service_tier'] = payload['service_tier']
    if payload.get('reasoning', {}).get('effort') is not None:
        outgoing['reasoning_effort'] = payload['reasoning']['effort']
    if payload.get('max_output_tokens') is not None:outgoing['max_tokens']=payload['max_output_tokens']
    tools = [{"type": "function", "function": {key: value for key, value in tool.items() if key != "type"}} for tool in payload.get("tools", [])]
    if tools:
        outgoing["tools"] = tools
    if "tool_choice" in payload:
        choice = payload["tool_choice"]
        outgoing["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}} if isinstance(choice, dict) else choice
    return outgoing


def response_events(response, names, *, response_id=None, message_id=None, text_streamed=False):
    choices = response.get("choices", [])
    if len(choices) != 1 or choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
        raise GatewayError("Chat provider did not complete its response", 502)
    message = choices[0].get("message", {})
    output = []
    content = message.get("content")
    if content:
        if not isinstance(content, str):
            raise GatewayError("Chat provider returned unsupported output", 502)
        output.append({"type": "message", "id": message_id or "msg_" + secrets.token_hex(12), "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": content, "annotations": []}]})
    reasoning = message.get("reasoning_content") or message.get("reasoning")
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
    response_id = response_id or "resp_chat_bridge_" + secrets.token_hex(12)
    events = [] if text_streamed else [{"type": "response.created", "response": {"id": response_id, "status": "in_progress", "output": []}}]
    for index, item in enumerate(output):
        initial = dict(item)
        if item["type"] == "function_call":
            initial["arguments"] = ""
        else:
            initial["content"] = []
        if text_streamed and item['type'] == 'message':
            events.append({'type': 'response.output_text.done', 'output_index': index, 'content_index': 0, 'item_id': item['id'], 'text': content})
            events.append({"type": "response.output_item.done", "output_index": index, "item": item})
            continue
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


def stream_response_events(stream, names):
    """Forward text immediately; validate complete tool calls before releasing them."""
    response_id = 'resp_chat_bridge_' + secrets.token_hex(12)
    message_id = 'msg_' + secrets.token_hex(12)
    def event(value):
        return ('data: ' + json.dumps(value) + '\n\n').encode(), value
    def progress():
        # SSE comments are discarded before the desktop's idle timer resets.
        return event({'type': 'response.in_progress', 'response': {'id': response_id, 'status': 'in_progress', 'output': []}})
    yield event({'type': 'response.created', 'response': {'id': response_id, 'status': 'in_progress', 'output': []}})
    text, reasoning, calls = [], [], {}
    usage, finish = {}, None
    frame, frame_size, total = [], 0, 0
    while True:
        line = stream.readline(2 * 1024 * 1024 + 1)
        if not line:
            raise GatewayError('Chat provider stream ended without completing', 502)
        total += len(line)
        frame_size += len(line)
        if frame_size > 2 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise GatewayError('Chat provider stream exceeded the limit', 502)
        if line.strip():
            frame.append(line.rstrip(b'\r\n'))
            continue
        data = b'\n'.join(part[5:].lstrip(b' ') for part in frame if part.startswith(b'data:'))
        frame, frame_size = [], 0
        if not data:
            yield progress()
            continue
        if data == b'[DONE]':
            break
        try:
            chunk = json.loads(data)
        except (ValueError, UnicodeError):
            raise GatewayError('Chat provider returned invalid streaming data', 502) from None
        if not isinstance(chunk, dict) or chunk.get('error'):
            raise GatewayError('Chat provider could not complete the response', 502)
        if isinstance(chunk.get('usage'), dict):
            usage = chunk['usage']
        choices = chunk.get('choices', [])
        if not choices:
            yield progress()
            continue
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict) or choices[0].get('index', 0) != 0:
            raise GatewayError('Chat provider returned invalid choices', 502)
        choice = choices[0]
        if finish is not None:
            raise GatewayError('Chat provider returned data after completion', 502)
        delta = choice.get('delta', {})
        if not isinstance(delta, dict):
            raise GatewayError('Chat provider returned invalid delta', 502)
        content = delta.get('content')
        if content is not None and not isinstance(content, str):
            raise GatewayError('Chat provider returned unsupported output', 502)
        if content:
            if not text:
                yield event({'type': 'response.output_item.added', 'output_index': 0, 'item': {'type': 'message', 'id': message_id, 'role': 'assistant', 'status': 'in_progress', 'content': []}})
            text.append(content)
            yield event({'type': 'response.output_text.delta', 'output_index': 0, 'content_index': 0, 'item_id': message_id, 'delta': content})
        thought = delta.get('reasoning_content') or delta.get('reasoning')
        if thought is not None:
            if not isinstance(thought, str):
                raise GatewayError('Chat provider returned invalid reasoning', 502)
            reasoning.append(thought)
        fragments = delta.get('tool_calls') or []
        if not isinstance(fragments, list):
            raise GatewayError('Chat provider returned invalid function output', 502)
        for fragment in fragments:
            if not isinstance(fragment, dict) or type(fragment.get('index')) is not int or not 0 <= fragment['index'] < 128:
                raise GatewayError('Chat provider returned invalid function index', 502)
            call = calls.setdefault(fragment['index'], {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
            if fragment.get('type', 'function') != 'function' or not isinstance(fragment.get('function', {}), dict):
                raise GatewayError('Chat provider returned invalid function output', 502)
            for source, destination, key in ((fragment, call, 'id'), (fragment.get('function', {}), call['function'], 'name'), (fragment.get('function', {}), call['function'], 'arguments')):
                value = source.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise GatewayError('Chat provider returned invalid function fragment', 502)
                    destination[key] += value
        finish = choice.get('finish_reason')
        if finish is not None and finish not in {'stop', 'tool_calls'}:
            raise GatewayError('Chat provider did not complete its response', 502)
        if not content:
            yield progress()
    message = {'content': ''.join(text), 'reasoning_content': ''.join(reasoning), 'tool_calls': [calls[index] for index in sorted(calls)]}
    if any(not call['id'] or not call['function']['name'] for call in message['tool_calls']):
        raise GatewayError('Chat provider returned incomplete function output', 502)
    reply = {'choices': [{'finish_reason': finish, 'message': message}], 'usage': usage}
    # response.created was already sent, including for tool-only generations.
    yield from response_events(reply, names, response_id=response_id, message_id=message_id, text_streamed=True)
