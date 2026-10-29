import requests
import cbor
import time

from utils.response import Response

def download(url, config, logger=None):
    host, port = config.cache_server
    resp = None
    for attempt in range(5): #try up to 5 times in case the connection drops (vpn/cache hiccup)
        try:
            resp = requests.get(
                f"http://{host}:{port}/",
                params=[("q", f"{url}"), ("u", f"{config.user_agent}")],
                timeout=60) #give up on this try if the cache doesnt answer in 60 sec, so the worker cant get stuck forever
            break #got an answer so stop retrying
        except requests.exceptions.RequestException as e:
            if logger:
                logger.error(f"Connection problem w/ {url} (try {attempt + 1} of 5): {e}")
            time.sleep(10 * (attempt + 1)) #wait a lil longer each time before trying again
    if resp is None:
        #never got an answer after 5 tries, so skip this url instead of crashing the whole crawl
        #status 0 = no answer at all, scraper only uses status 200 so it just gets skipped
        return Response({
            "error": f"Could not reach the cache for {url}.",
            "status": 0,
            "url": url})
    try:
        if resp and resp.content:
            return Response(cbor.loads(resp.content))
    except (EOFError, ValueError) as e:
        pass
    logger.error(f"Spacetime Response error {resp} with url {url}.")
    return Response({
        "error": f"Spacetime Response error {resp} with url {url}.",
        "status": resp.status_code,
        "url": url})
