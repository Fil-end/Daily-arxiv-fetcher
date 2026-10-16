"""Read official arXiv search results when the Atom API is unavailable."""
import re
from datetime import datetime
from html.parser import HTMLParser


class Element:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, tag=None, css=None):
        found = []
        for child in self.children:
            if isinstance(child, Element):
                if (tag is None or child.tag == tag) and (css is None or css in child.attrs.get("class", "").split()):
                    found.append(child)
                found.extend(child.find(tag, css))
        return found

    def text(self):
        return "".join(c.text() if isinstance(c, Element) else c for c in self.children)


class SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs)
        self.stack[-1].children.append(element)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for n in range(len(self.stack) - 1, 0, -1):
            if self.stack[n].tag == tag:
                del self.stack[n:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def web_query(query):
    """Select the first OR group as a broad search anchor."""
    group = query.split(")", 1)[0] if query.startswith("(") else query.split(" AND ", 1)[0]
    return re.findall(r'\b(all|au):("[^"]+"|[^\s()]+)', group)


def parse_results(markup):
    parser = SearchParser()
    parser.feed(markup)
    clean = lambda text: " ".join(text.split())
    entries = []
    results = parser.root.find("li", "arxiv-result")
    if not results and not re.search(r"(no results|sorry, your query|0 results)", markup, re.I):
        raise ValueError("Unrecognized arXiv search page; refusing to treat it as empty")
    for result in results:
        titles = result.find("p", "title")
        summaries = result.find("span", "abstract-full")
        links = [e.attrs["href"] for e in result.find("a") if re.match(r"https://arxiv.org/abs/", e.attrs.get("href", ""))]
        date = re.search(r"Submitted\s+(\d{1,2}\s+\w+,\s+\d{4})", clean(result.text()))
        if not titles or not summaries or not links or not date:
            raise ValueError("Incomplete arXiv search metadata")
        summary = clean(summaries[0].text())
        summary = re.sub(r"\s*△?\s*Less$", "", summary)
        authors = result.find("p", "authors")
        published = datetime.strptime(date[1], "%d %B, %Y").strftime("%Y-%m-%dT00:00:00Z")
        entries.append({"id": links[0], "link": links[0], "title": clean(titles[0].text()),
                        "summary": summary, "published": published, "updated": published,
                        "authors": [{"name": clean(a.text())} for a in authors[0].find("a")] if authors else [],
                        "tags": [{"term": clean(t.text())} for t in result.find("span", "tag")]})
    return entries


def search(get, query, start, end, rows):
    """Use a bounded, serial search with the same submission-date window."""
    entries = []
    anchors = web_query(query)
    if not anchors:
        raise ValueError("Cannot translate the arXiv query to web search")
    terms = {}
    for n, (field, term) in enumerate(anchors):
        terms.update({f"terms-{n}-operator": "OR" if n else "AND",
                      f"terms-{n}-term": term, f"terms-{n}-field": "author" if field == "au" else "all"})
    for offset in range(0, max(50, rows), 50):
        with get("https://arxiv.org/search/advanced", params={
            "advanced": "", **terms, "classification-include_cross_list": "include",
            "date-filter_by": "date_range", "date-from_date": start, "date-to_date": end,
            "date-date_type": "submitted_date", "abstracts": "show", "size": 50,
            "order": "-announced_date_first", "start": offset,
        }) as response:
            page = parse_results(response.text)
        entries.extend(e for e in page if start <= e["published"][:10] <= end)
        if len(page) < 50 or len(entries) >= rows:
            break
    return entries[:rows]
