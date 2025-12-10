# ADS-B to CoT Converter

Converts ADS-B aircraft data to Cursor on Target (CoT) events for TAK servers.

## Environment Variables

### TAK Server Configuration
- `COT_URL` - TAK server URL (default: `tls://localhost:8089`)
  - For local development: `tls://host.docker.internal:8089` (macOS/Windows)
  - For server deployment: `tls://your-server-ip:8089` or `tls://localhost:8089`
- `PYTAK_TLS_CLIENT_PASSWORD` - TLS client certificate password (default: `atakatak`)
- `PYTAK_TLS_CLIENT_CERT` - Path to TLS client certificate (default: `certs/user1.p12`)

### ADS-B Data Source Configuration
- `ADSB_LAT` - Latitude for ADS-B data center point (default: `40.7128` - NYC)
- `ADSB_LON` - Longitude for ADS-B data center point (default: `-74.0060` - NYC)
- `ADSB_DISTANCE` - Radius in miles around center point (default: `15`)
- `ADSB_API_URL` - ADS-B API base URL (default: `https://opendata.adsb.fi/api/v2`)
- `SLEEP_INTERVAL` - Seconds between data polls (default: `3`)

### CoT Configuration
- `UID_KEY` - How to generate unique IDs: ICAO, REG, or FLIGHT (default: `ICAO`)
- `COT_STALE` - CoT event timeout in seconds (default: `300`)
- `COT_HOST_ID` - Host identifier for CoT events (default: `adsb-feeder`)
- `FEED_URL` - Feed source identifier (default: `opendata.adsb.fi/NYC`)

### Filtering Options
- `ALT_UPPER` - Maximum altitude filter, 0 = no limit (default: `0`)
- `ALT_LOWER` - Minimum altitude filter, 0 = no limit (default: `0`)
- `DEBUG` - Enable debug logging: true/false (default: `false`)

## Usage Examples

### Basic run (uses defaults - NYC area)
```bash
docker run -d --name adsb-cot-converter adsb-to-cot
```

### Custom TAK server
```bash
docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://localhost:8089" \
 -e PYTAK_TLS_CLIENT_PASSWORD="atakatak" \
 adsb-to-cot
```

### Custom location (Los Angeles area)
```bash
docker run -d --name adsb-cot-converter \
 -e ADSB_LAT="34.0522" \
 -e ADSB_LON="-118.2437" \
 -e ADSB_DISTANCE="25" \
 -e SLEEP_INTERVAL="5" \
 adsb-to-cot
```

### High altitude filtering (commercial aircraft only)
```bash
docker run -d --name adsb-cot-converter \
 -e ALT_LOWER="10000" \
 -e ALT_UPPER="45000" \
 adsb-to-cot
```

### TAK server on host machine
```bash
docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://host.docker.internal:8089" \
 adsb-to-cot
```

## Troubleshooting

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