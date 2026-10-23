import hashlib
import re
from collections import Counter
from urllib.parse import parse_qsl, unquote, urlparse

MIN_WORDS = 50
MAX_QUERY_VARIANTS = 30
# near duplicates can differ at, at most three of the 64 fingerprint bits.
MAX_SIMHASH_DISTANCE = 3

# function to filter out traps
def is_trap(url):
    parsed = urlparse(url)
    path = unquote(parsed.path).lower()
    # ignore empty parts caused by leading, trailing, or consecutive slashes.
    segments = [part for part in path.split('/') if part]

    # limit URL length and path depth to avoid crawler traps
    if len(url) > 2048 or len(segments) > 20:
        return True
    
    # reject paths where the same directory name appears more than 3 times
    if any(count >= 3 for count in Counter(segments).values()):
        return True
    
    # extract query paramters into name, value pairs
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keys = [key.lower() for key, value in pairs]
    # rejects URLs that have more than 8 parameters or if a parameter name appears more than once
    if len(pairs) > 8 or len(keys) != len(set(keys)):
        return True
    


    # Skip calendar date navigation to prevent endless crawling loops. 
    # Ordinary event detail URLs can still pass.
    calendar = re.search(r'/(?:events?|calendar)(?:/|$)', path)
    date_path = re.search(r'/(?:day|week|month)/|/\d{4}[-/]\d{1,2}', path)
    date_query = any(key in {'date', 'eventdate', 'tribe-bar-date',
                            'month', 'year', 'day'} for key in keys)
    
    return bool(calendar and (date_path or date_query))


def simhash(words):
    # create 64-bit fingerprint in order to determine pages with similar text.
    votes = [0] * 64

    # repeated words get more weight
    for word, frequency in Counter(words).items():
        # each word given a consistent hash value across all runs
        digest = hashlib.sha256(word.encode('utf-8')).digest()
        value = int.from_bytes(digest[:8], 'big')

        # standard simhash method, using word frequencies as weights
        for bit in range(64):
            votes[bit] += frequency if value & (1 << bit) else -frequency
            
    # combine votes into page's fingerprint
    return sum(1 << bit for bit, vote in enumerate(votes) if vote > 0)


class CrawlFilters:
    def __init__(self):
        # start with empty state for a new crawl.
        self.restore({})

    def restore(self, data):
        # restore from saved state if crawl was interrupt, or start with empty state if no saved data available
        self.checksums = set(data.get('checksums', []))
        self.fingerprints = set(data.get('fingerprints', []))
        self.query_urls = {key: set(values) for key, values in
                           data.get('query_urls', {}).items()}
        self.bands = {}

        # rebuild the lookup table for finding similar fingerprints
        for fingerprint in self.fingerprints:
            self._index(fingerprint)

    def getSaveData(self):
        # convert sets into lists so state can be saved as a JSON
        return {'checksums': sorted(self.checksums),
                'fingerprints': sorted(self.fingerprints),
                'query_urls': {key: sorted(values)
                               for key, values in self.query_urls.items()}}

    def allowUrl(self, url):
        """Limit query combinations per host and path, even if parameter names change."""
        parsed = urlparse(url)
        if not parsed.query:
            return True
        
        # create shared key for URLs with same host and path, ommitting query parameters
        family = parsed.netloc.lower() + parsed.path

        # avoid counting reordered query paramters as a different variation
        identity = repr(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        seen = self.query_urls.setdefault(family, set())

        # allow existing variations without going towards the 30-query limit
        if identity in seen:
            return True
        if len(seen) >= MAX_QUERY_VARIANTS:
            return False
        
        # count the combination, before the page is downloaded.
        seen.add(identity)
        return True

    def _index(self, fingerprint):
        # fingerprints within 3 differing bits share a section
        for band in range(4):
            key = (band, (fingerprint >> (16 * band)) & 65535)
            self.bands.setdefault(key, set()).add(fingerprint)

    def shouldFollowLink(self, words):
        # skip pages with too little useful text
        if len(words) < MIN_WORDS or len(set(words)) < 15:
            return False
        
        # catch soft error pages that somehow succeeded and still returned HTTP 200
        # make sure to check all first 20 words to avoid error messages that occur a bit later in the page
        opening = ' '.join(words[:20])
        if re.search(r'\b(?:404 not found|page not found|access denied|'
                     r'page does not exist|page cannot be found)\b', opening):
            return False
        

        # skip pages with text we have already seen
        checksum = hashlib.sha256(' '.join(words).encode('utf-8')).hexdigest()
        if checksum in self.checksums:
            return False
        
        # find fingerprints that could belong to similar pages
        fingerprint = simhash(words)
        candidates = set()
        for band in range(4):
            key = (band, (fingerprint >> (16 * band)) & 65535)
            candidates.update(self.bands.get(key, ()))

        self.checksums.add(checksum)


        # skip near duplicates (over 3 differing bits)
        if any(bin(fingerprint ^ previous).count('1') <= MAX_SIMHASH_DISTANCE
               for previous in candidates):
            return False
        
        # ONLY save the fingerprints for pages that we accept
        self.fingerprints.add(fingerprint)
        self._index(fingerprint)
        return True
