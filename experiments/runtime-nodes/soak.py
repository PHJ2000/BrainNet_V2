"""One-hour bounded-rate soak: real runtimes, HTTP mock AI, 100 real websocket clients.

Use a separate disposable database so correctness probes cannot reset soak state.
"""
import asyncio
from collections import Counter
import contextlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from uuid import uuid4
import asyncpg
import httpx
from websockets.asyncio.client import connect
from urllib.parse import urlencode

async def main():
    if os.getenv('ALLOW_TEST_DATABASE_RESET')!='1' or not os.environ['POSTGRES_URL'].endswith('/brainnet_soak'):
        raise SystemExit('Explicit disposable brainnet_soak DB required')
    token=subprocess.check_output(['python','spring/vertical-slice/contract_seed.py'],text=True).strip()
    duration=int(os.getenv('SOAK_SECONDS','3600'))
    clients=int(os.getenv('SOAK_WEBSOCKETS','100'))
    rate=float(os.getenv('SOAK_OPERATIONS_PER_SECOND','5'))
    apis=[os.environ['FASTAPI_BASE_URL'],os.environ['SPRING_BASE_URL']]
    path=Path(os.getenv('RESULTS_DIR','experiments/runtime-nodes/results/final-2026-09-12'))
    path.mkdir(parents=True,exist_ok=True)
    counters=[Counter() for _ in range(clients)]
    errors=Counter()
    error_details=[]
    latency=[]
    lag=[]
    event_times={}
    samples=[]
    completed=0
    loop_lag=[]
    db=await asyncpg.connect(os.environ['POSTGRES_URL'])
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=10) as http, contextlib.AsyncExitStack() as stack:
        async def receive(index,socket):
            try:
                async for raw in socket:
                    event=json.loads(raw)
                    kind=event.get('type')
                    if kind in ('node.created','node.deleted'):
                        counters[index][kind]+=1
                        if index==0 and kind=='node.created':
                            event_times[event['node_id']]=time.perf_counter()
            except Exception as error:
                errors['websocket:'+type(error).__name__]+=1
        sockets=[]
        ws_url=apis[0].replace('http','ws',1)+'/projects/1/ws?'+urlencode({'token':token})
        for _ in range(clients):
            sockets.append(await stack.enter_async_context(connect(ws_url,open_timeout=30,ping_timeout=30)))
        readers=[asyncio.create_task(receive(i,s)) for i,s in enumerate(sockets)]
        started=time.perf_counter()
        async def heartbeat():
            while True:
                before=time.perf_counter()
                await asyncio.sleep(.1)
                loop_lag.append(max(0,(time.perf_counter()-before-.1)*1000))
        heartbeat_task=asyncio.create_task(heartbeat())
        async def operation(index):
            nonlocal completed
            key=str(uuid4())
            body={'parent_id':12, 'ai_prompt':'soak AI'} if index%3==0 else {'parent_id':12,'content':'soak node'}
            before=time.perf_counter()
            writer=apis[index%2]
            rollback=apis[1-index%2]
            phase='create'
            try:
                created=await http.post(writer+'/projects/1/nodes',json=body,headers={'Idempotency-Key':key})
                assert created.status_code==201,('create',created.status_code,created.text)
                node=created.json()[0]
                assert node['tags']==[101]
                phase='replay'
                replay=await http.post(rollback+'/projects/1/nodes',json=body,headers={'Idempotency-Key':key})
                assert replay.status_code==201 and replay.json()==created.json(),('replay',replay.status_code)
                phase='delete'
                deleted=await http.delete(apis[0]+f'/projects/1/nodes/{node["id"]}')
                assert deleted.status_code==204,('delete',deleted.status_code)
                latency.append((time.perf_counter()-before)*1000)
                phase='event'
                async with asyncio.timeout(10):
                    while node['id'] not in event_times: await asyncio.sleep(.01)
                lag.append((event_times.pop(node['id'])-before)*1000)
                completed+=1
            except Exception as error:
                errors[type(error).__name__+':'+str(error)[:140]]+=1
                error_details.append({'elapsed_seconds':round(time.perf_counter()-started,3),
                    'operation':index,'phase':phase,'writer':writer,'key':key,'body':body,
                    'error':type(error).__name__+':'+str(error)[:300]})

        active=set()
        index=0
        next_sample=0
        try:
            while time.perf_counter()-started < duration:
                now=time.perf_counter()-started
                if len(active)<10 and now >= index/rate:
                    task=asyncio.create_task(operation(index))
                    active.add(task)
                    task.add_done_callback(active.discard)
                    index+=1
                if now>=next_sample:
                    try:
                        health=(await http.get(apis[0]+'/health/events')).json()
                        provider_health=(await http.get(os.getenv('PROVIDER_HEALTH_URL','http://provider:8090/health'))).json()
                        if db.is_closed(): db=await asyncpg.connect(os.environ['POSTGRES_URL'])
                        db_states=[dict(r) for r in await db.fetch("SELECT state,wait_event_type,count(*) AS count FROM pg_stat_activity WHERE datname=current_database() GROUP BY state,wait_event_type")]
                    except Exception as error:
                        errors['monitor:'+type(error).__name__]+=1
                        health={'ready':False,'probe_error':type(error).__name__}
                        provider_health={}
                        db_states=[]
                    sample={'elapsed_seconds':round(now,1),'completed':completed,'errors':sum(errors.values()),'event_health':health,'db_connections':db_states,
                            'client_loop_lag_max_ms':round(max(loop_lag,default=0),3),
                            'provider_loop_lag_max_ms':provider_health.get('event_loop_lag_max_ms')}
                    samples.append(sample)
                    (path/'soak-progress.json').write_text(json.dumps(sample,indent=2)+'\n')
                    print(json.dumps(sample),flush=True)
                    next_sample+=60
                await asyncio.sleep(.01)
            await asyncio.gather(*active)
            try:
                async with asyncio.timeout(30):
                    while any(c['node.created']<completed or c['node.deleted']<completed for c in counters): await asyncio.sleep(.1)
            except TimeoutError:
                errors['event_drain:TimeoutError']+=1
            try:
                if db.is_closed(): db=await asyncpg.connect(os.environ['POSTGRES_URL'])
                remaining=await db.fetchval('SELECT count(*) FROM node')
                pending=await db.fetchval('SELECT count(*) FROM outbox_event WHERE published_at IS NULL')
            except Exception as error:
                errors['database_audit:'+type(error).__name__]+=1
                remaining=pending=None
            def p95(values): return sorted(values)[int((len(values)-1)*.95)] if values else None
            result={'duration_seconds':round(time.perf_counter()-started,3),'target_seconds':duration,'websocket_clients':clients,
                    'target_operations_per_second':rate,'attempted_operations':index,'completed_operations':completed,
                    'errors':dict(errors),'error_details':error_details,
                    'client_event_counts':[dict(counter) for counter in counters],
                    'operation_p95_ms':p95(latency),'creation_to_event_p95_ms':p95(lag),
                    'delivered_events':sum(sum(c.values()) for c in counters),'expected_delivered_events':completed*clients*2,
                    'every_client_complete':all(c['node.created']==completed and c['node.deleted']==completed for c in counters),
                    'client_loop_lag_p95_ms':p95(loop_lag),'client_loop_lag_max_ms':max(loop_lag,default=0),
                    'remaining_nodes':remaining,'pending_events':pending,'samples':samples}
            (path/'soak.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            assert not errors and result['every_client_complete'] and remaining==3 and pending==0, 'Soak gate failed; complete evidence saved in ' + str(path/'soak.json')
            print('SOAK PASSED '+json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task,return_exceptions=True)
            for reader in readers: reader.cancel()
            await asyncio.gather(*readers,return_exceptions=True)
            await db.close()

if __name__=='__main__': asyncio.run(main())
