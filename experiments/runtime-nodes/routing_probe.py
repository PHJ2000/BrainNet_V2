"""Verify a fixed project allowlist and idempotent rollback through the real proxy."""
import json
import os
from pathlib import Path
import sys
import httpx

phase=sys.argv[1]
assert phase in ('baseline','canary','rollback')
path=Path('experiments/runtime-nodes/results/final-2026-09-12/routing-state.json')
path.parent.mkdir(parents=True,exist_ok=True)
state={} if phase=='baseline' else json.loads(path.read_text())
with httpx.Client(base_url=os.environ['PROXY_BASE_URL'],headers={'Authorization':'Bearer '+os.environ['JWT_TOKEN']},timeout=10) as client:
    for key,body in [('rollout-normal',{'content':'rollout','parent_id':12}),('rollout-ai',{'ai_prompt':'rollout AI','parent_id':12})]:
        response=client.post('/projects/1/nodes',json=body,headers={'Idempotency-Key':key})
        assert response.status_code==201,response.text
        assert response.headers['x-brainnet-writer']==('spring' if phase=='canary' else 'fastapi'),response.headers
        if key in state: assert response.json()==state[key]
        else: state[key]=response.json()
    control=client.post('/projects/3/nodes',json={'content':'control root'},headers={'Idempotency-Key':'control-root'})
    assert control.status_code==201 and control.headers['x-brainnet-writer']=='fastapi',control.text
    if phase in ('canary','rollback'):
        for key,body in [('canary-normal',{'content':'canary','parent_id':12}),('canary-ai',{'ai_prompt':'canary AI','parent_id':12})]:
            response=client.post('/projects/1/nodes',json=body,headers={'Idempotency-Key':key})
            assert response.status_code==201,response.text
            assert response.headers['x-brainnet-writer']==('spring' if phase=='canary' else 'fastapi')
            if key in state: assert response.json()==state[key]
            else: state[key]=response.json()
path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
print(f'Routing {phase} passed: normal/AI same owner, project isolation, response replay across cutover')
