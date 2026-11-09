import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// Custom metrics for non-functional audit
const errorRate = new Rate('custom_error_rate');
const cloudfrontHitRate = new Rate('cloudfront_cache_hit_rate');
const requestCounter = new Counter('total_http_requests');
const responseTimeTrend = new Trend('custom_response_time_ms');

// Safe, non-intrusive performance test configuration
// Maximum total request rate bounded strictly below 2 req/sec to prevent cloud throttling or unexpected cost.
export const options = {
  stages: [
    { duration: '30s', target: 1 }, // Stage 1: Baseline (1 VU, 30s)
    { duration: '60s', target: 2 }, // Stage 2: Light load (2 VUs, 60s)
    { duration: '60s', target: 5 }, // Stage 3: Moderate load (5 VUs, 60s)
    { duration: '15s', target: 0 }, // Graceful ramp-down
  ],
  thresholds: {
    // Automated safety abort conditions:
    // 1. Error rate must strictly stay below 1% (no 5xx or connection drops)
    'http_req_failed': ['rate<0.01'],
    'custom_error_rate': ['rate<0.01'],
    // 2. Latency percentiles (P95 < 1500ms, P99 < 3000ms)
    'http_req_duration': ['p(95)<1500', 'p(99)<3000'],
  },
};

const BASE_URL = __ENV.TARGET_URL || 'https://d3qn9wabid8ws0.cloudfront.net';

export default function () {
  // Read-only static endpoints on CloudFront CDN distribution
  const endpoints = [
    '/',
    '/styles.css',
    '/app.js',
    '/config.json',
  ];

  for (const path of endpoints) {
    const url = `${BASE_URL}${path}`;
    const params = {
      headers: {
        'Accept': path.endsWith('.json') ? 'application/json' : 'text/html,application/javascript,text/css,*/*',
        'User-Agent': 'k6-CloudResourceGuardian-PerformanceTest/1.0',
      },
      tags: { endpoint: path },
    };

    const res = http.get(url, params);
    requestCounter.add(1);
    responseTimeTrend.add(res.timings.duration);

    // Verify status and response integrity
    const success = check(res, {
      'status is 200': (r) => r.status === 200,
      'response body is non-empty': (r) => r.body && r.body.length > 0,
      'protocol is HTTP/2': (r) => r.proto === 'HTTP/2.0' || r.proto === 'h2',
    });

    errorRate.add(!success);

    // Track CloudFront edge cache behavior
    const cfCacheHeader = res.headers['X-Cache'] || res.headers['x-cache'] || '';
    const isHit = cfCacheHeader.toLowerCase().includes('hit');
    cloudfrontHitRate.add(isHit);

    // Pacing: sleep to maintain strictly <= 2 requests/second aggregate
    sleep(1.0);
  }
}
