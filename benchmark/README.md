# TAK Server Benchmark Tool

A benchmarking tool for measuring TAK server CoT message throughput and performance.

## Quick Start

### Build

From the `benchmark/` directory, build with parent context to include `requirements.txt`:

```bash
docker build -t tak-benchmark -f Dockerfile ..
```

### Run

```bash
# Basic run (100 messages at 10/sec)
docker run --rm \
  -e COT_URL=tls://tak-server-tak-1:8089 \
  -e PYTAK_TLS_CLIENT_PASSWORD=atakatak \
  -e BENCHMARK_RATE=50 \
  -e BENCHMARK_COUNT=0 \
  tak-benchmark

# High throughput test (5000 messages, unlimited rate)
docker run --rm \
  -v /path/to/certs:/usr/src/app/certs:ro \
  -e COT_URL=tls://your-tak-server:8089 \
  -e BENCHMARK_COUNT=5000 \
  -e BENCHMARK_RATE=0 \
  tak-benchmark

# Duration-based test (60 seconds at 50 msg/sec)
docker run --rm \
  -v /path/to/certs:/usr/src/app/certs:ro \
  -e COT_URL=tls://your-tak-server:8089 \
  -e BENCHMARK_COUNT=0 \
  -e BENCHMARK_DURATION=60 \
  -e BENCHMARK_RATE=50 \
  tak-benchmark
```

## Environment Variables

### Connection Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `COT_URL` | `tls://localhost:8089` | TAK server URL |
| `PYTAK_TLS_CLIENT_CERT` | `/usr/src/app/certs/client.p12` | Path to client certificate |
| `PYTAK_TLS_CLIENT_PASSWORD` | (required) | Certificate password - pass at runtime |
| `PYTAK_TLS_DONT_CHECK_HOSTNAME` | `1` | Skip hostname verification |
| `PYTAK_TLS_DONT_VERIFY` | `1` | Skip certificate verification |

### Benchmark Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHMARK_COUNT` | `100` | Number of messages to send (0 = unlimited) |
| `BENCHMARK_RATE` | `10` | Messages per second (0 = unlimited/max speed) |
| `BENCHMARK_DURATION` | (empty) | Max duration in seconds (optional) |
| `BASE_LAT` | `40.7128` | Base latitude for generated CoT points |
| `BASE_LON` | `-74.0060` | Base longitude for generated CoT points |
| `DEBUG` | (empty) | Set to any value to enable debug logging |

## Output

The benchmark outputs statistics upon completion:

```
============================================================
BENCHMARK RESULTS
============================================================
Total Messages Sent:    1,000
Total Errors:           0
Duration:               10.05 seconds
Throughput:             99.50 messages/second

Latency (queue time):
  Min:                  0.01 ms
  Max:                  2.34 ms
  Avg:                  0.15 ms
============================================================
```

## Local Usage (without Docker)

```bash
# Install dependencies
pip install -r ../requirements.txt

# Run benchmark
python benchmark.py --count 1000 --rate 100

# Run with options
python benchmark.py \
  --count 5000 \
  --rate 0 \
  --cot-url tls://tak-server:8089 \
  --cert /path/to/cert.p12 \
  --password atakatak

# Duration-based
python benchmark.py --duration 60 --rate 50
```

### CLI Options

```
--count, -c       Number of messages to send (default: 100)
--rate, -r        Messages per second, 0 for unlimited (default: 10)
--duration, -d    Maximum duration in seconds (optional)
--cot-url         TAK server URL (overrides COT_URL env var)
--cert            Path to TLS client certificate
--password        TLS certificate password
--base-lat        Base latitude for generated points (default: 40.7128)
--base-lon        Base longitude for generated points (default: -74.0060)
--debug           Enable debug logging
```

## Test Scenarios

### Baseline Test
```bash
docker run --rm -v ./certs:/usr/src/app/certs:ro \
  -e COT_URL=tls://server:8089 \
  -e BENCHMARK_COUNT=100 \
  -e BENCHMARK_RATE=10 \
  tak-benchmark
```

### Stress Test
```bash
docker run --rm -v ./certs:/usr/src/app/certs:ro \
  -e COT_URL=tls://server:8089 \
  -e BENCHMARK_COUNT=10000 \
  -e BENCHMARK_RATE=0 \
  tak-benchmark
```

### Sustained Load Test
```bash
docker run --rm -v ./certs:/usr/src/app/certs:ro \
  -e COT_URL=tls://server:8089 \
  -e BENCHMARK_DURATION=300 \
  -e BENCHMARK_RATE=100 \
  tak-benchmark
```



docker build -t tak-benchmark -f Dockerfile ..

docker run --network tak-server_tak --name cot-benchmark \
  -e COT_URL=tls://tak-server-tak-1:8089 \
  -e PYTAK_TLS_CLIENT_PASSWORD=atakatak \
  -e BENCHMARK_RATE=10 \
  -e BENCHMARK_COUNT=0 \
  -e UNIQUE_TRACKS=1000 \
  tak-benchmark