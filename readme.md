# Basic run (uses defaults)

docker run -d --name adsb-cot-converter adsb-to-cot

# Run with custom TAK server

docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://localhost:8089" \
 -e PYTAK_TLS_CLIENT_PASSWORD="atakatak" \
 adsb-to-cot

# If TAK server is on the host machine

docker run -d --name adsb-cot-converter \
 -e COT_URL="tls://host.docker.internal:8089" \
 adsb-to-cot

  <!--  -->

./update-container.sh



echo 'docker stop adsb-cot-converter 2>/dev/null; docker build -t adsb-to-cot . && docker run -d --name adsb-cot-converter --rm adsb-to-cot' > update-container.sh && chmod +x update-container.sh



<!-- pushing to github container registry -->
`docker push ghcr.io/sheldon-st/adsb-to-cot`