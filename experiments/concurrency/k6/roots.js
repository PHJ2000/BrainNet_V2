import exec from 'k6/execution';
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const baseUrl = __ENV.BASE_URL;
const projectId = __ENV.PROJECT_ID;
const created = new Counter('roots_created');
const conflicts = new Counter('roots_conflict');
const unexpected = new Counter('roots_unexpected');

http.setResponseCallback(http.expectedStatuses({ min: 200, max: 299 }, 409));

export const options = {
  scenarios: {
    roots: {
      executor: 'shared-iterations',
      vus: 100,
      iterations: 100,
      maxDuration: '30s',
    },
  },
  discardResponseBodies: true,
};

export default function () {
  const response = http.post(`${baseUrl}/roots/${projectId}`);
  check(response, {
    'created or conflict': (r) => r.status === 201 || r.status === 409,
  });
  if (response.status === 201) {
    created.add(1);
  } else if (response.status === 409) {
    conflicts.add(1);
  } else {
    unexpected.add(1);
  }
}
