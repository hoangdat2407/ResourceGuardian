import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('api_error_rate');
const apiLatency = new Trend('api_latency_ms');

export const options = {
  stages: [
    { duration: '30s', target: 1 }, // Stage 1: Baseline (1 VU)
    { duration: '60s', target: 2 }, // Stage 2: Light load (2 VUs)
    { duration: '60s', target: 5 }, // Stage 3: Moderate load (5 VUs)
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    'http_req_failed': ['rate<0.01'],
    'api_error_rate': ['rate<0.01'],
    'http_req_duration': ['p(95)<2000'],
  },
};

const API_BASE_URL = __ENV.API_URL || 'https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com';
const TOKEN = __ENV.AUTH_TOKEN || '';

export default function () {
  if (!TOKEN) {
    // If no token is provided, verify that the API Gateway authorizer correctly returns 401 Unauthorized
    const res = http.get(`${API_BASE_URL}/me`);
    check(res, {
      'unauthorized without token is 401': (r) => r.status === 401,
    });
    sleep(1.0);
    return;
  }

  const authHeaders = {
    'Authorization': `Bearer ${TOKEN}`,
    'Content-Type': 'application/json',
  };

  // 1. GET /me
  let res = http.get(`${API_BASE_URL}/me`, { headers: authHeaders, tags: { endpoint: '/me' } });
  apiLatency.add(res.timings.duration);
  check(res, {
    'GET /me status is 200': (r) => r.status === 200,
  });
  sleep(1.0);

  // 2. GET /findings
  res = http.get(`${API_BASE_URL}/findings`, { headers: authHeaders, tags: { endpoint: '/findings' } });
  apiLatency.add(res.timings.duration);
  check(res, {
    'GET /findings status is 200': (r) => r.status === 200,
  });
  sleep(1.0);

  // 3. GET /history
  res = http.get(`${API_BASE_URL}/history?limit=20`, { headers: authHeaders, tags: { endpoint: '/history' } });
  apiLatency.add(res.timings.duration);
  check(res, {
    'GET /history status is 200': (r) => r.status === 200,
  });
  sleep(1.0);
}
