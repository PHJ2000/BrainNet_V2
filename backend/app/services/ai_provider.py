"""Provider transport and response parsing. Database sessions never enter this module."""
import os
import re
from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from app.core.errors import error_detail

_ai_client: AsyncOpenAI | None = None

def _raise(status, code, message):
    raise HTTPException(status, detail=error_detail(code, message))

def _get_ai_client():
    global _ai_client
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        _raise(503, 'AI_PROVIDER_NOT_CONFIGURED', 'AI provider is not configured')
    if _ai_client is None:
        _ai_client = AsyncOpenAI(api_key=api_key, base_url=os.getenv('OPENAI_BASE_URL'),
                                 timeout=float(os.getenv('OPENAI_TIMEOUT_SECONDS','30')), max_retries=0)
    return _ai_client

async def close_ai_client():
    global _ai_client
    client, _ai_client = _ai_client, None
    if client is not None:
        await client.close()

async def generate_content(prompt: str) -> str:
    try:
        response = await _get_ai_client().chat.completions.create(
            model=os.getenv('OPENAI_MODEL','gpt-3.5-turbo'),
            messages=[{'role':'system','content':'당신은 창의적인 아이디어를 제공하는 도우미입니다.'},
                      {'role':'user','content':f'다음 주제와 관련된 새로운 아이디어를 간략한 문장 형태로 한 개 작성해줘: {prompt}'}],
            max_tokens=256, temperature=.7)
        answer = response.choices[0].message.content
        if not isinstance(answer,str) or not answer.strip():
            raise ValueError('empty provider content')
        normalized = re.sub(r'^\d+\.\s*','',answer.strip().splitlines()[0]).strip()
        if not normalized:
            raise ValueError('empty normalized content')
        return normalized
    except APITimeoutError:
        _raise(504, 'AI_PROVIDER_TIMEOUT', 'AI provider request timed out')
    except (APIConnectionError, APIStatusError, OpenAIError, ValueError, IndexError, AttributeError, TypeError):
        _raise(502, 'AI_PROVIDER_UNAVAILABLE', 'AI provider request failed')
