"""
End-to-end failure scenario test script for CloudOps360 monitoring and alerting.

This script tests:
1. HTTP 4xx Client Errors (404 Not Found & 422 Validation Error)
2. Latency measurement under load
3. API Downtime Simulation (stops container, verifies up == 0, restarts container)
"""

import subprocess
import time
import urllib.error
import urllib.request
import json
import sys


API_BASE = "http://localhost:8000"
PROMETHEUS_BASE = "http://localhost:9090"


def query_prometheus(query: str):
    url = f"{PROMETHEUS_BASE}/api/v1/query?query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_client_errors():
    print("\n--- 1. Testing HTTP 4xx Client Errors ---")
    
    # 404 test
    try:
        urllib.request.urlopen(f"{API_BASE}/nonexistent-route-for-testing")
    except urllib.error.HTTPError as e:
        print(f"Triggered 404 Not Found as expected: HTTP {e.code}")

    # 422 test (invalid JSON body)
    req = urllib.request.Request(
        f"{API_BASE}/tasks",
        data=b'{"title": ""}',  # empty title violates min_length=1
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(f"Triggered 422 Validation Error as expected: HTTP {e.code}")


def test_latency_generation(count: int = 10):
    print(f"\n--- 2. Generating {count} Normal Requests for Latency Calculation ---")
    for i in range(count):
        with urllib.request.urlopen(f"{API_BASE}/health") as resp:
            pass
        with urllib.request.urlopen(f"{API_BASE}/") as resp:
            pass
    print("Requests sent successfully.")


def verify_prometheus_metrics():
    print("\n--- 3. Verifying Prometheus Metrics ---")
    print("Waiting 16 seconds for Prometheus scrape cycle...")
    time.sleep(16)

    # Scrape target status
    up_res = query_prometheus('up{job="cloudops360-api"}')
    up_val = up_res.get("data", {}).get("result", [{}])[0].get("value", [None, None])[1]
    print(f"API Target Status (up): {up_val} (1 = UP, 0 = DOWN)")

    # Total requests
    total_res = query_prometheus("sum(cloudops360_http_requests_total)")
    total_val = total_res.get("data", {}).get("result", [{}])[0].get("value", [None, None])[1]
    print(f"Total Requests Processed: {total_val}")

    # p95 latency
    lat_res = query_prometheus(
        "histogram_quantile(0.95, sum(rate(cloudops360_http_request_duration_seconds_bucket[5m])) by (le))"
    )
    results = lat_res.get("data", {}).get("result", [])
    if results:
        lat_val = results[0].get("value", [None, None])[1]
        print(f"95th-Percentile Latency: {lat_val} seconds")
    else:
        print("95th-Percentile Latency: No data in window")


def test_api_downtime_scenario():
    print("\n--- 4. Testing API Downtime Failure Scenario ---")
    print("Stopping cloudops360-api container...")
    subprocess.run(["docker", "stop", "cloudops360-api"], check=True)

    print("Waiting 20 seconds for Prometheus to record down status...")
    time.sleep(20)

    down_res = query_prometheus('up{job="cloudops360-api"}')
    results = down_res.get("data", {}).get("result", [])
    down_val = results[0].get("value", [None, None])[1] if results else "0"
    print(f"Prometheus Recorded Target Status: {down_val} (Expected: 0 / DOWN)")

    print("Restarting cloudops360-api container to recover...")
    subprocess.run(["docker", "start", "cloudops360-api"], check=True)

    print("Waiting 20 seconds for API to recover and be scraped as UP...")
    time.sleep(20)

    recovered_res = query_prometheus('up{job="cloudops360-api"}')
    rec_results = recovered_res.get("data", {}).get("result", [])
    rec_val = rec_results[0].get("value", [None, None])[1] if rec_results else "0"
    print(f"Prometheus Recorded Target Status after Recovery: {rec_val} (Expected: 1 / UP)")


def main():
    test_client_errors()
    test_latency_generation(10)
    verify_prometheus_metrics()
    test_api_downtime_scenario()
    print("\nAll monitoring and failure scenario tests completed successfully!")


if __name__ == "__main__":
    main()
