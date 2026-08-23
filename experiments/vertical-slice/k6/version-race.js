import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const updated = new Counter('updated');
const conflict = new Counter('conflict');
const unexpected = new Counter('unexpected');
http.setResponseCallback(http.expectedStatuses(200, 409));

export const options = { scenarios: { race: { executor: 'shared-iterations', vus: 100, iterations: 100, maxDuration: '30s' } }, discardResponseBodies: true };

export default function () {
  const response = http.patch(`${__ENV.BASE_URL}/projects/${__ENV.PROJECT_ID}/nodes/${__ENV.NODE_ID}`, JSON.stringify({ expected_version: 0, content: `winner-${__VU}` }), { headers: { 'Content-Type': 'application/json' } });
  check(response, { expected: (r) => r.status === 200 || r.status === 409 });
  if (response.status === 200) updated.add(1); else if (response.status === 409) conflict.add(1); else unexpected.add(1);
}
