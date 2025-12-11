docker run --name adsb-cot-converter -d \                     
  --network tak-server_tak \
  -e COT_URL="tls://tak-server-tak-1:8089" \
  -e ADSB_ENDPOINT="mil" \
  -e ADSB_API_URL="https://api.adsb.lol/v2" \
  -e SLEEP_INTERVAL="5" \
  adsb-to-cot