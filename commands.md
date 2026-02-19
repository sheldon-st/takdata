# Multi-Source Configuration Example with Independent Polling
# Military aircraft polled every 10 seconds (slower updates)
# Regional detail polled every 3 seconds (faster, real-time updates)

docker run --name adsb-cot-converter -d \
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
      "name": "adsb.lol-regional",
      "base_url": "https://api.adsb.lol/v2",
      "endpoint": "point",
      "lat": "40.7128",
      "lon": "-74.0060",
      "distance": "25",
      "sleep_interval": 3
    }
  ]' \
  adsb-to-cot

# Legacy single source (for reference)
# docker run --name adsb-cot-converter -d \
#   --network tak-server_tak \
#   -e COT_URL="tls://tak-server-tak-1:8089" \
#   -e ADSB_ENDPOINT="mil" \
#   -e ADSB_API_URL="https://api.adsb.lol/v2" \
#   -e SLEEP_INTERVAL="5" \
#   adsb-to-cot




# Multi-source military endpoints for redundancy/better coverage
docker run --name adsb-cot-converter -d \
  --network tak-server_tak \
  -e COT_URL="tls://tak-server-tak-1:8089" \
  -e ADSB_SOURCES_JSON='[
    {
      "name": "adsb.fi-military",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "mil",
      "sleep_interval": 3
    },
    {
      "name": "adsb.lol-military",
      "base_url": "https://api.adsb.lol/v2",
      "endpoint": "mil",
      "sleep_interval": 2
    }
  ]' \
  adsb-to-cot


  docker run --name adsb-cot-converter -d \
  --network tak-server_tak \
  -e COT_URL="tls://tak-server-tak-1:8089" \
  -e ADSB_SOURCES_JSON='[
    {
      "name": "adsb.fi-military",
      "base_url": "https://opendata.adsb.fi/api/v2",
      "endpoint": "mil",
      "sleep_interval": 3
    }
  ]' \
  adsb-to-cot