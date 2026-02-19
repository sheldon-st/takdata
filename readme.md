# ADS-B to CoT Converter

Converts ADS-B aircraft data to Cursor on Target (CoT) events for TAK servers.

## Features

- **Multi-Source Aggregation**: Simultaneously fetch data from multiple ADS-B sources (adsb.fi, adsb.lol, etc.)
- **Automatic Deduplication**: Intelligently merges aircraft data from multiple sources, keeping the most recent/complete information
- **Concurrent Streaming**: All data sources are queried in parallel for maximum efficiency
- **Flexible Configuration**: Support for geographic areas, military aircraft, and point-based queries
- **Data Quality Improvement**: Combine multiple sources for the same region to fill coverage gaps

## Environment Variables

### TAK Server Configuration
- `COT_URL` - TAK server URL (default: `tls://localhost:8089`)
  - For local development: `tls://host.docker.internal:8089` (macOS/Windows)
  - For server deployment: `tls://your-server-ip:8089` or `tls://localhost:8089`
- `PYTAK_TLS_CLIENT_PASSWORD` - TLS client certificate password (default: `atakatak`)
- `PYTAK_TLS_CLIENT_CERT` - Path to TLS client certificate (default: `certs/user1.p12`)

### ADS-B Data Source Configuration

#### Multi-Source Mode (Recommended)
Use `ADSB_SOURCES_JSON` to configure multiple concurrent data sources with automatic deduplication:
- `ADSB_SOURCES_JSON` - JSON array of data source configurations (see examples below)

Each source in the JSON array supports:
- `name` - Friendly name for the source (required)
- `base_url` - API base URL (required)
- `endpoint` - Endpoint type: `geo`, `point`, or `mil` (required)
- `sleep_interval` - Polling interval in seconds for this specific source (optional, defaults to global `SLEEP_INTERVAL`)
- `lat`, `lon`, `distance` - Geographic parameters (for `geo`/`point` endpoints)

#### Legacy Single Source Mode
For backward compatibility, configure a single source using:
- `ADSB_ENDPOINT` - API endpoint type: `geo` for geographic area, `point` for point-based, or `mil` for military aircraft (default: `geo`)
- `ADSB_LAT` - Latitude for ADS-B data center point (default: `40.7128` - NYC) *(only for `geo`/`point` endpoint)*
- `ADSB_LON` - Longitude for ADS-B data center point (default: `-74.0060` - NYC) *(only for `geo`/`point` endpoint)*
- `ADSB_DISTANCE` - Radius in miles around center point (default: `15`) *(only for `geo`/`point` endpoint)*
- `ADSB_API_URL` - ADS-B API base URL (default: `https://opendata.adsb.fi/api/v2`)

### General Configuration
- `SLEEP_INTERVAL` - Seconds between data polls (default: `3`)

### Queue Configuration
- `MAX_OUT_QUEUE` - Maximum size of outbound queue to TAK server (default: `1000`)
  - Increase this if you see "Queue full, dropping oldest data" warnings
  - Higher values use more memory but prevent data loss
- `MAX_IN_QUEUE` - Maximum size of inbound queue for processing (default: `1000`)
  - Adjust based on the number of aircraft being tracked

### CoT Configuration
- `UID_KEY` - How to generate unique IDs: ICAO, REG, or FLIGHT (default: `ICAO`)
- `COT_STALE` - CoT event timeout in seconds (default: `300`)
- `COT_HOST_ID` - Host identifier for CoT events (default: `adsb-feeder`)
- `FEED_URL` - Feed source identifier (default: `multi-source`)

### Filtering Options
- `ALT_UPPER` - Maximum altitude filter, 0 = no limit (default: `0`)
- `ALT_LOWER` - Minimum altitude filter, 0 = no limit (default: `0`)
- `DEBUG` - Enable debug logging: true/false (default: `false`)

## Usage Examples

### Multi-Source Configuration (Recommended)

#### Example 1: Military + Regional Coverage with Independent Polling
Combines military aircraft from adsb.fi (polled every 10 seconds) with detailed regional coverage from adsb.lol (polled every 3 seconds):
```bash
docker run -d --name adsb-cot-converter \
  --network tak-server_tak \
  -e COT_URL="tls://tak-server-tak-1:8089" \
  -e ADSB_SOURCES_JSON='[
    {
      "name": "adsb.fi-military",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "mil",
      "sleep_interval": 10
    },
    {
      "name": "adsb.lol-nyc-detail",
      "base_url": "https://api.adsb.lol/v2",
      "endpoint": "point",
      "lat": "40.7128",
      "lon": "-74.0060",
      "distance": "25",
      "sleep_interval": 3
    }
  ]' \
  adsb-to-cot
```

#### Example 2: Multiple Regional Sources for Better Coverage
Aggregate data from multiple sources for the same region to improve data quality:
```bash
docker run -d --name adsb-cot-converter \
  -e COT_URL="tls://localhost:8089" \
  -e ADSB_SOURCES_JSON='[
    {
      "name": "adsb.fi-nyc",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "geo",
      "lat": "40.7128",
      "lon": "-74.0060",
      "distance": "30"
    },
    {
      "name": "adsb.lol-nyc",
      "base_url": "https://api.adsb.lol/v2",
      "endpoint": "point",
      "lat": "40.7128",
      "lon": "-74.0060",
      "distance": "30"
    }
  ]' \
  adsb-to-cot
```

#### Example 3: Multiple Geographic Regions
Monitor multiple geographic areas simultaneously:
```bash
docker run -d --name adsb-cot-converter \
  -e COT_URL="tls://localhost:8089" \
  -e ADSB_SOURCES_JSON='[
    {
      "name": "east-coast",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "geo",
      "lat": "40.7128",
      "lon": "-74.0060",
      "distance": "50"
    },
    {
      "name": "west-coast",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "geo",
      "lat": "34.0522",
      "lon": "-118.2437",
      "distance": "50"
    },
    {
      "name": "military-global",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "mil"
    }
  ]' \
  adsb-to-cot
```

### Legacy Single Source Examples

#### Basic run (uses defaults - NYC area)
```bash
docker run -d --name adsb-cot-converter adsb-to-cot
```

#### Custom TAK server
```bash
docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://localhost:8089" \
 -e PYTAK_TLS_CLIENT_PASSWORD="atakatak" \
 adsb-to-cot
```

#### Custom location (Los Angeles area)
```bash
docker run -d --name adsb-cot-converter \
 -e ADSB_LAT="34.0522" \
 -e ADSB_LON="-118.2437" \
 -e ADSB_DISTANCE="25" \
 -e SLEEP_INTERVAL="5" \
 adsb-to-cot
```

#### High altitude filtering (commercial aircraft only)
```bash
docker run -d --name adsb-cot-converter \
 -e ALT_LOWER="10000" \
 -e ALT_UPPER="45000" \
 adsb-to-cot
```

#### Military aircraft tracking (worldwide)
```bash
docker run -d --name adsb-cot-converter \
 -e ADSB_ENDPOINT="mil" \
 adsb-to-cot
```

#### TAK server on host machine
```bash
docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://host.docker.internal:8089" \
 adsb-to-cot
```

## Troubleshooting

### "Queue full, dropping oldest data" Warning

This warning occurs when aircraft data is being generated faster than it can be transmitted to the TAK server. Solutions:

1. **Increase queue size** (recommended):
   ```bash
   docker run -d --name adsb-cot-converter \
     -e COT_URL="tls://localhost:8089" \
     -e MAX_OUT_QUEUE=2000 \
     -e MAX_IN_QUEUE=2000 \
     -e ADSB_SOURCES_JSON='[...]' \
     adsb-to-cot
   ```

2. **Reduce polling frequency**:
   - Increase `sleep_interval` for each data source in `ADSB_SOURCES_JSON`
   - Or increase global `SLEEP_INTERVAL` value

3. **Check network connection**:
   - Slow network to TAK server can cause queue buildup
   - Verify TAK server is responding quickly

4. **Reduce data sources**:
   - If tracking too many regions, consider removing some sources
   - Focus on priority geographic areas

### DNS Resolution Error: "Name or service not known"

This error typically occurs when running the container on a Linux server where `host.docker.internal` doesn't resolve. Solutions:

1. **Set the correct COT_URL** (recommended):
   ```bash
   # Replace with your actual TAK server IP/hostname
   docker run -e COT_URL="tls://192.168.1.100:8089" adsb-to-cot
   ```

2. **For TAK server on same machine**:
   ```bash
   # Option A: Use host networking
   docker run --network host -e COT_URL="tls://localhost:8089" adsb-to-cot
   
   # Option B: Use Docker bridge gateway IP
   docker run -e COT_URL="tls://172.17.0.1:8089" adsb-to-cot
   ```

3. **Add host.docker.internal support on Linux**:
   ```bash
   docker run --add-host host.docker.internal:host-gateway adsb-to-cot
   ```

### SSL/TLS Errors: "tlsv1 alert internal error"

This error occurs when the client certificate is missing or invalid. Solutions:

1. **Add a valid client certificate**:
   ```bash
   # Copy your .p12 certificate to the certs directory
   cp /path/to/your/certificate.p12 certs/user1.p12
   docker build -t adsb-to-cot .
   docker run -e COT_URL="tls://172.17.0.1:8089" adsb-to-cot
   ```

2. **Mount certificate at runtime**:
   ```bash
   docker run \
     -v /path/to/certificate.p12:/usr/src/app/certs/user1.p12 \
     -e COT_URL="tls://172.17.0.1:8089" \
     -e PYTAK_TLS_CLIENT_PASSWORD="your_cert_password" \
     adsb-to-cot
   ```

3. **For testing only - disable client certificates**:
   ```bash
   docker run \
     -e COT_URL="tls://172.17.0.1:8089" \
     -e PYTAK_TLS_DISABLE_CERT=true \
     adsb-to-cot
   ```
   ⚠️ **Warning**: Only use this for testing. Production TAK servers require valid certificates.

### Connection Refused

If you get "Connection refused", verify:
- TAK server is running and listening on the specified port
- Firewall rules allow the connection
- Certificate files are correctly mounted and accessible

  <!--  -->

./update-container.sh



echo 'docker stop adsb-cot-converter 2>/dev/null; docker build -t adsb-to-cot . && docker run -d --name adsb-cot-converter --rm adsb-to-cot' > update-container.sh && chmod +x update-container.sh



<!-- pushing to github container registry -->
`docker push ghcr.io/sheldon-st/adsb-to-cot`


docker build -t adsb-to-cot .         