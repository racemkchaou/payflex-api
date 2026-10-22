import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 20,
  duration: '20s',
  thresholds: {
    http_req_duration: ['p(95)<200'],   // 95 % des requetes sous 200 ms
    http_req_failed: ['rate<0.01'],     // taux d'erreur sous 1 %
  },
};

const BASE = __ENV.BASE_URL || 'http://localhost:8000';
const HEADERS = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  const created = http.post(
    `${BASE}/accounts`,
    JSON.stringify({ owner: 'Load', balance: 1000 }),
    HEADERS
  );
  check(created, { 'compte cree (201)': (r) => r.status === 201 });

  const res = http.get(`${BASE}/accounts/${created.json('id')}`);
  check(res, { 'compte lu (200)': (r) => r.status === 200 });

  http.get(`${BASE}/health`);
  sleep(0.1);
}