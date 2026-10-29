import re
import os
import json
from crawl_filters import CrawlFilters, is_trap
from collections import Counter
from urllib.parse import urlparse, urljoin, urldefrag
from html.parser import HTMLParser
#resources: https://docs.python.org/3/library/urllib.parse.html , https://docs.python.org/3/library/html.parser.html 

# Domain names to check for given in the assignment instructions
DOMAINS_USED =("ics.uci.edu","cs.uci.edu","informatics.uci.edu","stat.uci.edu") 
# HTML markup doesn't count as words
SKIP_TEXT_TAGS = ("script", "style", "noscript", "template")

class MainParser(HTMLParser): #
    def __init__(self): #helper function that goes tag by tag on page
        super().__init__()
        self.hrefs = [] #keeping <a> of href 
        self.text = [] #Stores visible text on the page
        self.skip_depth = 0 #Counts how many tags to skip
    def handle_starttag(self, tag, pairs): #called for opening tags
        if tag in SKIP_TEXT_TAGS:
            self.skip_depth += 1
        if tag == "a":
            for name, value in pairs: #pairs keeps what each href is , like [ (href, "/index.html")]
                if name == "href" and value:
                    self.hrefs.append(value.strip())
    def handle_endtag(self, tag): #Handles closing if it detects a skip tag
        if tag in SKIP_TEXT_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
    def handle_data(self, data): #Collects text between tags
        if self.skip_depth == 0:
            self.text.append(data)

STATS_FILE = "crawl_stats.json"
REPORT_FILE = "report.txt"
SAVE_EVERY = 25 

#English stop words list from https://www.ranks.nl/stopwords 
STOP_WORDS = frozenset("""
a about above after again against all am an and any are aren't as at be because been before being
below between both but by can't cannot could couldn't did didn't do does doesn't doing don't down
during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her
here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's
its itself let's me more most mustn't my myself no nor not of off on once only or other ought our
ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than
that that's the their theirs them themselves then there there's these they they'd they'll they're
they've this those through to too under until up very was wasn't we we'd we'll we're we've were
weren't what what's when when's where where's which while who who's whom why why's with won't would
wouldn't you you'd you'll you're you've your yours yourself yourselves
""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*") 

page_words = {} 
word_freq = Counter()
unsaved_pages = 0 
filters = CrawlFilters()

def tokenize(text):
    return TOKEN_RE.findall(text.lower())

def load_stats(): 
    global page_words, word_freq
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            data = json.load(f)
        page_words = data.get("page_words", {})
        word_freq = Counter(data.get("word_freq", {}))
        filters.restore(data.get("filters", {}))

def reset_stats(): 
    global page_words, word_freq, unsaved_pages
    page_words = {}
    word_freq = Counter()
    unsaved_pages = 0
    filters.restore({})
    if os.path.exists(STATS_FILE):
        os.remove(STATS_FILE)

def save_stats():
    global unsaved_pages
    tmp_path = STATS_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump({"page_words": page_words, "word_freq": word_freq,
                   "filters": filters.getSaveData()}, f)
    os.replace(tmp_path, STATS_FILE) 
    unsaved_pages = 0

def record_page(url, words):
    global unsaved_pages
    if url in page_words:
        return 
    page_words[url] = len(words)
    for word in words:
        if word in STOP_WORDS or len(word) < 2 or word.isdigit():
            continue
        word_freq[word] += 1
    unsaved_pages += 1
    if unsaved_pages >= SAVE_EVERY:
        save_stats()

def subdomain_counts(domain="ics.uci.edu"):
    counts = Counter()
    for url in page_words:
        host = (urlparse(url).hostname or "").lower()
        if host == domain or host.endswith("." + domain):
            counts[host] += 1
    return counts

def write_report():
    lines = []
    lines.append(f"1. Unique pages found: {len(page_words)}")
    lines.append("")

    if page_words:
        longest_url = max(page_words, key=page_words.get)
        lines.append(f"2. Longest page: {longest_url} ({page_words[longest_url]} words)")
    else:
        lines.append("2. Longest page: none")
    lines.append("")

    lines.append("3. 50 most common words (stop words removed):")
    for rank, (word, count) in enumerate(word_freq.most_common(50), 1):
        lines.append(f"   {rank}. {word}, {count}")
    lines.append("")

    subdomains = subdomain_counts()
    lines.append(f"4. Subdomains of ics.uci.edu: {len(subdomains)}")
    for host in sorted(subdomains):
        lines.append(f"http://{host}, {subdomains[host]}") 

    with open(REPORT_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")

load_stats()

def scraper(url, resp):
    links = extract_next_links(url, resp)
    return [link for link in dict.fromkeys(links)
            if is_valid(link) and filters.allowUrl(link)]

def decode_page(page_content): #turns the page bytes into text, either utf-8 or utf-16 (lecture 10)
    if page_content[:2] == b"\xff\xfe" or page_content[:2] == b"\xfe\xff":
        return page_content.decode("utf-16", errors="ignore") #utf-16 pages start w/ FF FE or FE FF so we know right away
    if b"\x00" in page_content[:1000]:
        return page_content.decode("utf-16-le", errors="ignore") #no mark but has zero bytes = utf-16, normal html never has zero bytes
    return page_content.decode("utf-8", errors="ignore") #everything else is utf-8 (plain ascii works w/ this too)

def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
    if resp.status != 200 or resp.raw_response is None:
        return [] #resp.status == 200 is OK so we  return nothing if it isn't 200 or there's nothing on the url/page
    page_content = resp.raw_response.content #using variable to make code easier to read
    if not page_content:
        return [] #if we get resp.status == 200 but the page has no content at all, then we return nothing
    if page_content.startswith(b"%PDF"):
        return [] #pdfs that snuck in w/o .pdf in the url, they always start w/ %PDF

    content_type = resp.raw_response.headers.get(
        "Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in {"text/html", "application/xhtml+xml"}:
        return []
    main_url = resp.raw_response.url or url
    if not is_valid(main_url):
        return []
    html = decode_page(page_content) #bytes to text w/ the right encoding
    if len(html) > 2 * 1024 * 1024:
        return [] #page is too big (over ~2 mil characters) so skip, we check after decoding bc utf-16 is double the bytes
    
    parser = MainParser() #call helper func
    parser.feed(html) #feed data to func
    parser.close() #end
    page_url = urldefrag(main_url)[0]
    words = tokenize(" ".join(parser.text))
    
    # count each URL even if its content duplicated another page
    record_page(page_url, words)
    important_words = [] #page words w/o stop words, used for near duplicate checking
    for word in words:
        if word not in STOP_WORDS:
            important_words.append(word)
    if not filters.shouldFollowLink(words, important_words):
        return []
    
    links_list = [] #all the urls we will get on the page
    for href in parser.hrefs:
        try:
            abs_url = urljoin(main_url, href) #relative links to absolute links
        except ValueError:
            continue #broken links skipped so nothing crashes
        abs_url, _ = urldefrag(abs_url) #remove fragments aka anything after the # in the url
        links_list.append(abs_url) #add to list of links
    return links_list

def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        parsed = urlparse(url)
        if parsed.scheme not in set(["http", "https"]):
            return False
        if not url.isascii(): #making sure url sent are all ascii valid
            return False

        # Check if URL is broken
        if parsed.hostname is None:
            return False 

        #Check if the hostname is an accepted domain or subdomain
        matched = False
        for domain in DOMAINS_USED:
            #If a match exists, then can immediately stop checking with other domains
            if parsed.hostname == domain or parsed.hostname.endswith("." + domain):
                matched = True
                break
        if not matched:
            return False
        if is_trap(url):
            return False

        #Skip duplicate pages from the same folder when they get re-sorted (traps)
        if re.search(r"C=[NMSD][;&]O=[AD]", parsed.query):
            return False
        
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz"
            + r"|c|cc|cpp|h|hpp|java|py|sh|cmake|o|class|in|am)$", parsed.path.lower())

    except TypeError:
        print ("TypeError for ", parsed)
        raise
    except ValueError:
        return False #cant read with urlparser so dont crawl

if __name__ == "__main__":
    #run `python3 scraper.py` anytime (even mid-crawl) to rebuild report.txt from the saved stats
    write_report()
    print(open(REPORT_FILE).read())