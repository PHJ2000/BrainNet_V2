"""Real HTTP clients against the local provider fixture; no external AI calls."""
import asyncio
import os
from uuid import uuid4
import asyncpg
import httpx

async def main():
    db=await asyncpg.connect(os.environ['POSTGRES_URL'])
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+os.environ['JWT_TOKEN']},timeout=10) as client:
        try:
            for runtime in (os.environ['FASTAPI_BASE_URL'],os.environ['SPRING_BASE_URL']):
                async def post(body,key,**kwargs):
                    return await client.post(runtime+'/projects/1/nodes',json=body,headers={'Idempotency-Key':key},**kwargs)
                for fault,status in (('[429]',502),('[timeout]',504),('[malformed]',502),('[empty]',502)):
                    key=str(uuid4())
                    response=await post({'ai_prompt':fault,'parent_id':12},key)
                    assert response.status_code==status,(runtime,fault,response.status_code,response.text)
                    assert response.json()['code'].startswith('AI_PROVIDER_'),response.text
                    assert await db.fetchval('SELECT count(*) FROM idempotency_request WHERE idempotency_key=$1',key)==0
                for prompt in ('normal','[blank-first]'):
                    response=await post({'ai_prompt':prompt,'parent_id':12},str(uuid4()))
                    assert response.status_code==201,response.text
                    assert response.json()[0]['content']=='검증용 아이디어',response.text
                    assert response.json()[0]['tags']==[101],response.text
                key=str(uuid4())
                body={'ai_prompt':'[cancel] '+key,'parent_id':12}
                try:
                    await post(body,key,timeout=.05)
                    raise AssertionError('provider fixture should outlast client timeout')
                except httpx.TimeoutException:
                    pass
                async with asyncio.timeout(10):
                    while True:
                        response=await post(body,key)
                        if response.status_code==201: break
                        assert response.status_code==409,response.text
                        await asyncio.sleep(.1)
                node_id=response.json()[0]['id']
                assert await db.fetchval('SELECT count(*) FROM outbox_event WHERE aggregate_id=$1 AND event_type=$2',node_id,'node.created')==1
                assert (await post(body,key)).json()==response.json()
                root=await post({'ai_prompt':'root AI'},str(uuid4()))
                assert root.status_code==201 and root.json()[0]['state']=='GHOST',root.text
                missing=await post({'ai_prompt':'invalid parent','parent_id':99999999},str(uuid4()))
                assert missing.status_code==404,missing.text
            print('Provider HTTP probe passed: success, blank first line, 429, timeout, malformed/empty, lost response replay, root and missing parent')
        finally:
            await db.close()

if __name__=='__main__': asyncio.run(main())
