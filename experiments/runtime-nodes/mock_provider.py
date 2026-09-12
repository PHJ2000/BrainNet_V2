"""Local OpenAI-compatible HTTP fault fixture. Never contacts an external provider."""
import asyncio
from collections import Counter
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn

app = FastAPI()
calls = Counter()

@app.get('/health')
async def health():
    return {'status': 'ok', 'calls': dict(calls)}

@app.post('/v1/chat/completions')
async def completion(request: Request):
    body = await request.json()
    prompt = body['messages'][-1]['content']
    calls[prompt] += 1
    if '[429]' in prompt:
        return JSONResponse(status_code=429, content={'error': {'message': 'fixture quota', 'type': 'rate_limit_error'}})
    if '[timeout]' in prompt:
        await asyncio.sleep(4)
    if '[malformed]' in prompt:
        return PlainTextResponse('{invalid', media_type='application/json')
    await asyncio.sleep(.2)
    answer = '' if '[empty]' in prompt else '1. 검증용 아이디어'
    if '[blank-first]' in prompt:
        answer = '\n1. 검증용 아이디어'
    return {'id': 'fixture', 'object': 'chat.completion', 'created': int(time.time()),
            'model': body.get('model', 'fixture'),
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': answer}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8090, access_log=False)
