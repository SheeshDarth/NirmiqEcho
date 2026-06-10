"""Web search and URL opening — uses the system default browser."""
from __future__ import annotations

import urllib.parse
import webbrowser


def web_search(query: str) -> str:
    if not query:
        return "What should I search for?"
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    webbrowser.open(url)
    return f"Searching for {query}."


def open_url(url: str) -> str:
    if not url:
        return "Which website?"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."
