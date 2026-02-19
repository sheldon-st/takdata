FROM python:3.9.6

RUN mkdir -p /usr/src/app/certs

WORKDIR /usr/src/app

# Copy files (paths relative to parent build context)
COPY benchmark/benchmark.py /usr/src/app/
COPY requirements.txt /usr/src/app/
COPY certs /usr/src/app/certs

# Install dependencies
RUN pip install -r requirements.txt

# Default environment variables - Connection
# Note: PYTAK_TLS_CLIENT_PASSWORD should be passed at runtime via -e flag
ENV COT_URL=tls://localhost:8089
ENV PYTAK_TLS_CLIENT_CERT=/usr/src/app/certs/funuser3.p12
ENV PYTAK_TLS_DONT_CHECK_HOSTNAME=1
ENV PYTAK_TLS_DONT_VERIFY=1

# Default environment variables - Benchmark Configuration
ENV BENCHMARK_COUNT=100
ENV BENCHMARK_RATE=10
ENV BENCHMARK_DURATION=""
ENV UNIQUE_TRACKS=10
ENV BASE_LAT=40.7128
ENV BASE_LON=-74.0060
ENV DEBUG=""

# Shell form required for conditional env var expansion (${VAR:+...} syntax)
# hadolint ignore=DL3025
CMD python ./benchmark.py \
    --count ${BENCHMARK_COUNT} \
    --rate ${BENCHMARK_RATE} \
    ${BENCHMARK_DURATION:+--duration ${BENCHMARK_DURATION}} \
    --unique-tracks ${UNIQUE_TRACKS} \
    --base-lat ${BASE_LAT} \
    --base-lon ${BASE_LON} \
    ${DEBUG:+--debug}
