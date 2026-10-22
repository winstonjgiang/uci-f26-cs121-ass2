from configparser import ConfigParser
from argparse import ArgumentParser

from utils.server_registration import get_cache_server
from utils.config import Config
from crawler import Crawler
import scraper


def main(config_file, restart):
    cparser = ConfigParser()
    cparser.read(config_file)
    config = Config(cparser)
    config.cache_server = get_cache_server(config, restart)
    if restart:
        #Delete old stats so that restarting shows stats from a new crawl
        scraper.reset_stats() 
    crawler = Crawler(config, restart)
    try:
        crawler.start()
    finally:
        #If the crawler stops, save the stats so that resuming will add to it
        scraper.save_stats()
        scraper.write_report()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--restart", action="store_true", default=False)
    parser.add_argument("--config_file", type=str, default="config.ini")
    args = parser.parse_args()
    main(args.config_file, args.restart)
