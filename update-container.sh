docker stop adsb-cot-converter 2>/dev/null; docker rm adsb-cot-converter 2>/dev/null; docker build -t adsb-to-cot . && docker run -d --name adsb-cot-converter --restart unless-stopped adsb-to-cot
