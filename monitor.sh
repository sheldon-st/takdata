#!/bin/bash

echo "Monitoring container health..."
while true; do
    if docker ps --filter name=adsb-cot-converter --quiet | grep -q .; then
        echo "$(date): Container is running"
    else
        echo "$(date): Container stopped/died!"
        echo "Exit code and logs:"
        docker ps -a --filter name=adsb-cot-converter
        echo "Last 50 lines of logs:"
        docker logs --tail 50 adsb-cot-converter
        break
    fi
    sleep 10
done
