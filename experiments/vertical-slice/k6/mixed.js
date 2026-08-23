import http from 'k6/http';
import { check } from 'k6';

const base = __ENV.BASE_URL;
const projectId = Number(__ENV.PROJECT_ID);
const firstNodeId = Number(__ENV.FIRST_NODE_ID);
let version = 0;

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '30s',
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: { http_req_failed: ['rate<0.01'] },
};

export default function () {
  const nodeId = firstNodeId + (__VU - 1);
  let response;
  if (__ITER % 5 === 4) {
    response = http.patch(
      `${base}/projects/${projectId}/nodes/${nodeId}`,
      JSON.stringify({ expected_version: version, content: `vu-${__VU}-iteration-${__ITER}`, pos_x: __ITER }),
      { headers: { 'Content-Type': 'application/json' }, tags: { operation: 'patch' } },
    );
    if (response.status === 200) version += 1;
  } else {
    response = http.get(`${base}/projects/${projectId}/nodes/${nodeId}`, { tags: { operation: 'get' } });
  }
  check(response, { 'status is 200': (r) => r.status === 200 });
}
