import http from 'k6/http';
import { check } from 'k6';

const scenario = __ENV.SCENARIO || 'io';
const baseUrl = __ENV.BASE_URL || 'http://fastapi-current:8080';
const delayMs = __ENV.DELAY_MS || (scenario === 'db' ? '50' : '200');

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '30s',
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const response = http.get(`${baseUrl}/${scenario}?delay_ms=${delayMs}`, {
    timeout: '10s',
    tags: { scenario },
  });
  check(response, { 'status is 200': (r) => r.status === 200 });
}
