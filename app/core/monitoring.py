"""
Monitoring and metrics collection for the application.
Provides Prometheus-compatible metrics and performance tracking.
"""
import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from collections import defaultdict

logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'schedule_api_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'schedule_api_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_REQUESTS = Gauge(
    'schedule_api_active_requests',
    'Number of requests currently being processed'
)

DB_QUERY_DURATION = Histogram(
    'schedule_db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation']
)

SCHEDULE_GENERATION_COUNT = Counter(
    'schedule_generation_total',
    'Total number of schedule generation attempts',
    ['status']  # success, failed
)

SCHEDULE_GENERATION_DURATION = Histogram(
    'schedule_generation_duration_seconds',
    'Time spent generating schedules'
)

PRACTICE_PERIODS_ACTIVE = Gauge(
    'schedule_practice_periods_active',
    'Number of active practice periods'
)

# In-memory stats for dashboard
class MetricsCollector:
    def __init__(self):
        self.endpoint_stats = defaultdict(lambda: {
            'count': 0,
            'total_duration': 0.0,
            'min_duration': float('inf'),
            'max_duration': 0.0,
            'errors': 0
        })
        self.slow_requests = []  # Last 10 slow requests
        self.max_slow_requests = 10

    def record_request(self, method: str, path: str, duration: float, status: int):
        key = f"{method} {path}"
        stats = self.endpoint_stats[key]
        stats['count'] += 1
        stats['total_duration'] += duration
        stats['min_duration'] = min(stats['min_duration'], duration)
        stats['max_duration'] = max(stats['max_duration'], duration)
        if status >= 400:
            stats['errors'] += 1

        # Track slow requests (>1s)
        if duration > 1.0:
            self.slow_requests.append({
                'method': method,
                'path': path,
                'duration': duration,
                'status': status,
                'timestamp': time.time()
            })
            # Keep only last N slow requests
            if len(self.slow_requests) > self.max_slow_requests:
                self.slow_requests.pop(0)

    def get_stats(self):
        result = {}
        for endpoint, stats in self.endpoint_stats.items():
            avg_duration = stats['total_duration'] / stats['count'] if stats['count'] > 0 else 0
            result[endpoint] = {
                'count': stats['count'],
                'avg_duration_ms': round(avg_duration * 1000, 2),
                'min_duration_ms': round(stats['min_duration'] * 1000, 2) if stats['min_duration'] != float('inf') else 0,
                'max_duration_ms': round(stats['max_duration'] * 1000, 2),
                'errors': stats['errors'],
                'error_rate': round(stats['errors'] / stats['count'] * 100, 2) if stats['count'] > 0 else 0
            }
        return result

    def get_slow_requests(self):
        return sorted(self.slow_requests, key=lambda x: x['duration'], reverse=True)


metrics_collector = MetricsCollector()


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect request metrics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        ACTIVE_REQUESTS.inc()
        start_time = time.time()

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Record metrics
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code
            ).inc()

            REQUEST_DURATION.labels(
                method=request.method,
                endpoint=request.url.path
            ).observe(duration)

            # Collect stats
            metrics_collector.record_request(
                request.method,
                request.url.path,
                duration,
                response.status_code
            )

            # Log slow requests
            if duration > 1.0:
                logger.warning(
                    "Slow request: %s %s took %.2fs (status=%s)",
                    request.method,
                    request.url.path,
                    duration,
                    response.status_code
                )

            return response
        except Exception as e:
            duration = time.time() - start_time
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.url.path,
                status=500
            ).inc()
            metrics_collector.record_request(request.method, request.url.path, duration, 500)
            raise
        finally:
            ACTIVE_REQUESTS.dec()


def get_metrics():
    """Get Prometheus metrics in text format."""
    return generate_latest()


def get_dashboard_stats():
    """Get dashboard-friendly statistics."""
    stats = metrics_collector.get_stats()
    slow_requests = metrics_collector.get_slow_requests()

    return {
        'endpoints': stats,
        'slow_requests': slow_requests,
        'summary': {
            'total_requests': sum(s['count'] for s in stats.values()),
            'total_errors': sum(s['errors'] for s in stats.values()),
            'avg_response_time_ms': round(
                sum(s['avg_duration_ms'] * s['count'] for s in stats.values()) /
                sum(s['count'] for s in stats.values())
                if sum(s['count'] for s in stats.values()) > 0 else 0,
                2
            )
        }
    }
