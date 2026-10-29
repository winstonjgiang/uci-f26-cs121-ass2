import re
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
    
    # reject paths where the same directory name appears 3 or more times
    segment_counts = {} #counts how many times each folder name shows up in the path
    for segment in segments:
        if segment in segment_counts:
            segment_counts[segment] = segment_counts[segment] + 1
        else:
            segment_counts[segment] = 1
        if segment_counts[segment] >= 3:
            return True #same folder 3+ times like /a/b/a/b/a means its looping, aka a trap
    
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

#duplicate detection below is made from scratch w/ NO libraries (none of these funcs use the imports up top)
#lecture 11 = checksum for exact duplicates, lecture 12 = simhash for near duplicates

def make_hash(word): #our own hash func, turns a word into a big number
    number = 0
    for letter in word:
        number = number * 31 + ord(letter) #each letter changes the number + order matters so "abc" and "cba" are different
        number = number % (2 ** 64) #keep it 64 bits every step, otherwise the number gets huge on big pages and it gets super slow
    number = number * 11400714819323198485 #multiply by a big odd number to mix up the bits
    number = number % (2 ** 64) #only keep the last 64 bits
    return number

def checksum(words): #exact duplicates (lecture 11), one number for the whole page
    all_text = " ".join(words)
    return make_hash(all_text) #same words in the same order = same number

def simhash(words): #near duplicates (lecture 12)
    weights = {} #step 1: count how many times each word shows up, thats the word's weight
    for word in words:
        if word in weights:
            weights[word] = weights[word] + 1
        else:
            weights[word] = 1

    totals = [0] * 64 #step 2: 64 totals, one for each bit
    for word in weights:
        word_hash = make_hash(word)
        for i in range(64):
            bit = (word_hash // (2 ** i)) % 2 #grabs bit i of the hash (0 or 1)
            if bit == 1:
                totals[i] = totals[i] + weights[word] #bit is 1 so add the weight
            else:
                totals[i] = totals[i] - weights[word] #bit is 0 so subtract the weight

    fingerprint = 0 #step 3: bit i of the fingerprint is 1 if totals[i] is positive, otherwise 0
    for i in range(64):
        if totals[i] > 0:
            fingerprint = fingerprint + 2 ** i
    return fingerprint

def count_different_bits(fingerprint1, fingerprint2): #how many of the 64 bits are different between 2 fingerprints
    different = 0
    for i in range(64):
        bit1 = (fingerprint1 // (2 ** i)) % 2
        bit2 = (fingerprint2 // (2 ** i)) % 2
        if bit1 != bit2:
            different = different + 1
    return different

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

    def shouldFollowLink(self, words, important_words): #important_words = words w/o stop words
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
        page_checksum = checksum(words) #our own checksum func from up top, no hashlib
        if page_checksum in self.checksums:
            return False
        
        # find fingerprints that could belong to similar pages
        fingerprint = simhash(important_words) #no stop words bc every page has tons of "the", "and" etc which makes different pages look alike (lecture 12 drops them too)
        candidates = set()
        for band in range(4):
            key = (band, (fingerprint >> (16 * band)) & 65535)
            candidates.update(self.bands.get(key, ()))

        self.checksums.add(page_checksum)

        # skip near duplicates (3 or less differing bits)
        for previous in candidates:
            if count_different_bits(fingerprint, previous) <= MAX_SIMHASH_DISTANCE:
                return False #too close to a page we already saw
        
        # ONLY save the fingerprints for pages that we accept
        self.fingerprints.add(fingerprint)
        self._index(fingerprint)
        return True
