import re
from urllib.parse import urlparse, urljoin, urldefrag
from html.parser import HTMLParser
#resources: https://docs.python.org/3/library/urllib.parse.html , https://docs.python.org/3/library/html.parser.html 

DOMAINS_USED =(".ics.uci.edu",".cs.uci.edu",".informatics.uci.edu",".stat.uci.edu") #given in instructions

class MainParser(HTMLParser): #
    def __init__(self): #helper function that goes tag by tag on page
        super().__init__()
        self.hrefs = [] #keeping <a> of href 
    def handle_starttag(self, tag, pairs): #called for opening tags
        if tag == "a":
            for name, value in pairs: #pairs keeps what each href is , like [ (href, "/index.html")]
                if name == "href" and value:
                    self.hrefs.append(value.strip())
    
def scraper(url, resp):
    links = extract_next_links(url, resp)
    return [link for link in links if is_valid(link)]

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
    
    main_url = resp.raw_response.url or url
    html = page_content.decode("utf-8", errors ="ignore") #making sure everything passed is valid characters (ASCII, UTF-8 standard)
    
    parser = MainParser() #call helper func
    parser.feed(html) #feed data to func
    parser.close() #end
    
    list = []#all the urls we will get on the page
    for href in parser.hrefs:
        try:
            abs_url = urljoin(main_url, href) #relative links to absolute links
        except ValueError:
            continue #broken links skipped so nothing crashes
        abs_url, _ = urldefrag(abs_url) #remove fragments aka anything after the # in the url
        list.append(abs_url) #add to list of links
    return list

def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        parsed = urlparse(url)
        if parsed.scheme not in set(["http", "https"]):
            return False
        if not url.ascii(): #making sure url sent are all ascii valid
            return False
        if parsed.hostname is None or not parsed.hostname.endswith(DOMAINS_USED):
            return False #check to make sure that the domains end with the 4 required ones only
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())

    except TypeError:
        print ("TypeError for ", parsed)
        raise
    except ValueError:
        return False #cant read with urlparser so dont crawl