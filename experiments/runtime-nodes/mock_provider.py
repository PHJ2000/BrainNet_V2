"""Local OpenAI-compatible HTTP fault fixture. Never contacts an external provider."""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
import uvicorn

loop_lag_max_ms = 0.0


@asynccontextmanager
async def lifespan(_app):
    async def heartbeat():
        global loop_lag_max_ms
        while True:
            before = time.perf_counter()
            await asyncio.sleep(.1)
            loop_lag_max_ms = max(loop_lag_max_ms, (time.perf_counter() - before - .1) * 1000)
    task = asyncio.create_task(heartbeat())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(lifespan=lifespan)
calls = Counter()

@app.get('/health')
async def health():
    return {'status': 'ok', 'calls': dict(calls), 'event_loop_lag_max_ms': round(loop_lag_max_ms, 3)}

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
