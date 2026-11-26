"""Read real Prometheus/Jaeger APIs and correlate selected traces with logs."""
import json
import base64
import re
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def find_traces(client, name, **filters):
    # Jaeger QueryService API v3: query_service.proto in jaegertracing/jaeger-idl.
    now = datetime.now(timezone.utc)
    params = {"query.serviceName": "observable-agent", "query.searchDepth": 200,
              "query.startTimeMin": (now - timedelta(hours=1)).isoformat(),
              "query.startTimeMax": now.isoformat(), **filters}
    response = client.get("http://localhost:16686/api/v3/traces", params=params)
    response.raise_for_status()
    envelopes = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    save(f"jaeger-{name}-raw.json", {"params": params, "envelopes": envelopes})
    grouped = {}
    for envelope in envelopes:
        for resource in envelope["result"].get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    trace_id = span["traceId"]
                    if not re.fullmatch(r"[0-9a-fA-F]{32}", trace_id):
                        trace_id = base64.b64decode(trace_id).hex()
                    item = grouped.setdefault(trace_id, {"traceID": trace_id, "spans": []})
                    item["spans"].append({"operationName": span["name"],
                        "duration": (int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1000,
                        "logs": span.get("events", []), "status": span.get("status", {})})
    return list(grouped.values())


def main():
    with httpx.Client(timeout=30) as client:
        queries = {
            "rps": 'sum(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
            "p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job="agent",route="/ask"}[1m])))',
            "avg_seconds": 'sum(rate(http_request_duration_seconds_sum{job="agent",route="/ask"}[1m])) / sum(rate(http_request_duration_seconds_count{job="agent",route="/ask"}[1m]))',
            "error_rate": 'sum(rate(http_requests_total{job="agent",route="/ask",status=~"5.."}[1m])) / sum(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
            "per_instance": 'sum by(instance)(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
            "tokens_per_second": 'sum by(type)(rate(llm_tokens_total{job="agent"}[1m]))',
            "instances_up": 'sum(up{job="agent"})',
        }
        stamp = datetime.now(timezone.utc).isoformat()
        snapshot = {"captured_at": stamp, "window": "1m", "queries": {}}
        for key, query in queries.items():
            response = client.get("http://localhost:9090/api/v1/query", params={"query": query})
            response.raise_for_status()
            snapshot["queries"][key] = {"promql": query, "response": response.json()}
        save("observability-snapshot.json", snapshot)
        if "--metrics-only" in sys.argv:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
            return
        traces = find_traces(client, "slow", **{"query.durationMin": "1s", "query.operationName": "POST /ask"})
        assert traces, "No slow traces exported"
        slow = max(traces, key=lambda t: max((s["duration"] for s in t["spans"] if s["operationName"] == "POST /ask"), default=0))
        error_traces = find_traces(client, "error", **{"query.attributes": json.dumps({"error": "true"})})
        error = next(t for t in error_traces if any(s.get("logs") and s["operationName"].startswith("chat ") for s in t["spans"]))
        save("jaeger-slow-trace.json", slow)
        save("jaeger-error-trace.json", error)
        result = subprocess.run(["docker", "compose", "-p", "k5-day14-observability", "-f", str(ROOT / "06-lab-complete/benchmark-observability/production/docker-compose.yml"), "logs", "--no-color", "--no-log-prefix", "agent"], capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        logs = []
        for line in (result.stdout + result.stderr).splitlines():
            try:
                logs.append(json.loads(line))
            except ValueError:
                pass
        selections = {"captured_at": stamp, "slow_candidates": len(traces), "error_candidates": len(error_traces)}
        for label, trace in [("slow", slow), ("error", error)]:
            root_span = next(s for s in trace["spans"] if s["operationName"] == "POST /ask")
            llm_span = max((s for s in trace["spans"] if s["operationName"].startswith("chat ")), key=lambda s: s["duration"])
            matched = [l for l in logs if l.get("trace_id") == trace["traceID"]]
            assert matched, f"No JSON log matching {label} trace"
            selections[label] = {"trace_id": trace["traceID"], "root_ms": root_span["duration"] / 1000,
                                 "llm_ms": llm_span["duration"] / 1000,
                                 "llm_span": llm_span["operationName"],
                                 "llm_fraction": llm_span["duration"] / root_span["duration"], "logs": matched}
        save("trace-evidence.json", selections)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(json.dumps(selections, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
