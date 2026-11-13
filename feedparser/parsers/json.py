# The JSON feed parser
# Copyright 2017 Beat Bolli
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS 'AS IS'
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import copy
import json

from ..datetimes import _parse_date
from ..sanitizer import sanitize_html
from ..urls import make_safe_absolute_uri, resolve_relative_uris
from ..util import FeedParserDict


class JSONParser:
    VERSIONS = {
        "https://jsonfeed.org/version/1": "json1",
        "https://jsonfeed.org/version/1.1": "json11",
    }
    FEED_FIELDS = (
        ("title", "title"),
        ("icon", "image"),
        ("home_page_url", "link"),
        ("description", "description"),
    )
    ITEM_FIELDS = (
        ("title", "title"),
        ("id", "guid"),
        ("url", "link"),
        ("summary", "summary"),
        ("external_url", "source"),
    )

    def __init__(self, baseuri=None, baselang=None, encoding=None):
        self.baseuri = baseuri or ""
        self.lang = baselang or None
        self.encoding = encoding or "utf-8"  # character encoding

        # Parsing options. These are set by ``api._parse_file_inplace()`` and
        # only affect the normalized JSON feed output (``self.normalize``).
        self.resolve_relative_uris = False
        self.sanitize_html = False
        self.normalize = False

        self.version = None
        self.feeddata = FeedParserDict()
        self.namespacesInUse = []
        self.entries = []

    def feed(self, file):
        data = json.load(file)

        v = data.get("version", "")
        try:
            self.version = self.VERSIONS[v]
        except KeyError:
            raise ValueError("Unrecognized JSONFeed version '%s'" % v)

        if self.normalize:
            self.feed_normalized(data)
            return

        for src, dst in self.FEED_FIELDS:
            if src in data:
                self.feeddata[dst] = data[src]
        if "author" in data:
            self.parse_author(data["author"], self.feeddata)
        # TODO: hubs; expired has no RSS equivalent

        self.entries = [self.parse_entry(e) for e in data["items"]]

    # ------------------------------------------------------------------
    # Normalized JSON feed parsing (opt-in via parse(normalize_json_feeds=True))
    # ------------------------------------------------------------------

    def feed_normalized(self, data):
        feed = self.feeddata

        # ``description`` is handled separately below so that it maps to the
        # Atom-style ``subtitle`` rather than the entry-level ``summary`` key.
        for src, dst in self.FEED_FIELDS:
            if src == "description":
                continue
            if src in data:
                feed[dst] = data[src]

        # The feed language is the HTTP Content-Language header, if present.
        # ``self.lang`` already holds that value.
        feed_links = []
        if "home_page_url" in data:
            feed["link"] = self._resolve_uri(data["home_page_url"])
            feed_links.append(
                FeedParserDict(
                    rel="alternate",
                    type="text/html",
                    href=feed["link"],
                )
            )
        if "feed_url" in data:
            feed_links.append(
                FeedParserDict(
                    rel="self",
                    type="application/feed+json",
                    href=self._resolve_uri(data["feed_url"]),
                )
            )
        if feed_links:
            feed["links"] = feed_links

        if "description" in data:
            feed["subtitle"] = data["description"]
            feed["subtitle_detail"] = self._make_text_detail(
                data["description"], "text/plain", self.lang
            )

        if "language" in data:
            self.lang = data["language"]
        if self.lang:
            feed["language"] = self.lang

        if "tags" in data:
            feed["tags"] = [
                self.parse_tag(t) for t in data["tags"] if isinstance(t, str)
            ]

        # JSON Feed 1.1 adds the ``authors`` array; the 1.0 ``author``
        # object remains as a single-author fallback.
        feed_authors = self.parse_authors(data)
        if feed_authors:
            feed["authors"] = feed_authors
            self._sync_author(feed, feed_authors)

        # TODO: hubs; expired has no RSS equivalent

        items = data.get("items")
        if not isinstance(items, list):
            items = []
        self.entries = []
        for item in items:
            if isinstance(item, dict):
                self.entries.append(self.parse_entry_normalized(item, feed_authors))

    def parse_entry_normalized(self, e, feed_authors):
        entry = FeedParserDict()
        for src, dst in self.ITEM_FIELDS:
            if src in e:
                entry[dst] = e[src]

        entry_lang = e.get("language") or self.lang
        if "language" in e:
            entry["language"] = e["language"]

        # ``guid`` is mapped to ``id`` by FeedParserDict.__setitem__().
        # Mark the id as a permalink only when the item has no explicit link.
        if "id" in e:
            entry["guidislink"] = "url" not in e

        links = []
        if "url" in e:
            entry["link"] = self._resolve_uri(e["url"])
            links.append(
                FeedParserDict(rel="alternate", type="text/html", href=entry["link"])
            )
        if "external_url" in e:
            links.append(
                FeedParserDict(
                    rel="related",
                    type="text/html",
                    href=self._resolve_uri(e["external_url"]),
                )
            )

        # ``content`` is always a list, retaining both the HTML and the
        # plain text variants when the feed provides both.
        content = []
        if "content_html" in e:
            content.append(self._make_html_detail(e["content_html"], entry_lang))
        if "content_text" in e:
            content.append(
                self._make_text_detail(e["content_text"], "text/plain", entry_lang)
            )
        if content:
            entry["content"] = content

        if "summary" in e:
            # JSON Feed summaries are plain text.
            entry["summary_detail"] = self._make_text_detail(
                e["summary"], "text/plain", entry_lang
            )
        elif content:
            # Mirror the Atom/RSS behavior of deriving a summary from content.
            entry["summary"] = content[0]["value"]
            entry["summary_detail"] = copy.deepcopy(content[0])

        # JSON Feed 1.1 renamed ``date_updated`` (1.0) to ``date_modified``.
        modified = e.get("date_modified")
        if modified is None:
            modified = e.get("date_updated")
        if modified is not None:
            entry["updated"] = modified
            entry["updated_parsed"] = _parse_date(modified)
        if "date_published" in e:
            entry["published"] = e["date_published"]
            entry["published_parsed"] = _parse_date(e["date_published"])

        if "tags" in e:
            entry["tags"] = [self.parse_tag(t) for t in e["tags"] if isinstance(t, str)]

        entry_authors = self.parse_authors(e)
        if entry_authors:
            # A per-entry author overrides the feed-level author entirely.
            entry["authors"] = entry_authors
            self._sync_author(entry, entry_authors)
        elif feed_authors:
            # Inherit the feed-level authors. Each entry gets its own copies
            # so that mutating one entry can never affect another entry.
            inherited = copy.deepcopy(feed_authors)
            entry["authors"] = inherited
            self._sync_author(entry, inherited)

        if "attachments" in e and isinstance(e["attachments"], list):
            for attachment in e["attachments"]:
                link = self.parse_attachment_normalized(attachment)
                if link is not None:
                    links.append(link)
        if links:
            entry["links"] = links

        return entry

    # ------------------------------------------------------------------
    # Normalized helpers
    # ------------------------------------------------------------------

    def _resolve_uri(self, uri):
        if not self.resolve_relative_uris:
            return uri
        return make_safe_absolute_uri(self.baseuri, uri.strip()) or uri

    def _make_html_detail(self, value, language):
        if self.resolve_relative_uris:
            value = resolve_relative_uris(
                value, self.baseuri, self.encoding, "text/html"
            )
        if self.sanitize_html:
            value = sanitize_html(value, self.encoding, "text/html")
        return FeedParserDict(
            value=value,
            type="text/html",
            base=self.baseuri,
            language=language,
        )

    def _make_text_detail(self, value, content_type, language):
        return FeedParserDict(
            value=value,
            type=content_type,
            base=self.baseuri,
            language=language,
        )

    def parse_authors(self, parent):
        """Build an ``authors`` list from a feed or item object.

        JSON Feed 1.1's ``authors`` array takes precedence over the 1.0
        single ``author`` object. Every returned dictionary is a fresh
        object so callers can mutate entries independently.
        """
        authors = []
        if isinstance(parent.get("authors"), list):
            for author in parent["authors"]:
                detail = self._author_detail(author)
                if detail is not None:
                    authors.append(detail)
        if not authors and isinstance(parent.get("author"), dict):
            detail = self._author_detail(parent["author"])
            if detail is not None:
                authors.append(detail)
        return authors

    @staticmethod
    def _author_detail(author):
        if not isinstance(author, dict):
            return None
        detail = FeedParserDict()
        name = author.get("name")
        if isinstance(name, str):
            detail["name"] = name
        url = author.get("url")
        if isinstance(url, str):
            if url.startswith("mailto:"):
                detail["email"] = url[7:]
            else:
                detail["href"] = url
        return detail or None

    @staticmethod
    def _sync_author(context, authors):
        """Populate the singular ``author``/``author_detail`` fields."""
        detail = authors[0]
        context["author_detail"] = copy.deepcopy(detail)
        name = detail.get("name")
        email = detail.get("email")
        if name and email:
            context["author"] = f"{name} ({email})"
        elif name:
            context["author"] = name
        elif email:
            context["author"] = email

    @staticmethod
    def parse_tag(tag):
        # JSON Feed tags are bare strings; RSS/Atom tags are dictionaries.
        return FeedParserDict(term=tag, scheme=None, label=None)

    def parse_attachment_normalized(self, attachment):
        if not isinstance(attachment, dict):
            return None
        url = attachment.get("url")
        mime_type = attachment.get("mime_type")
        if not isinstance(url, str) or not isinstance(mime_type, str):
            return None
        link = FeedParserDict(rel="enclosure")
        link["href"] = self._resolve_uri(url)
        link["type"] = mime_type
        size = attachment.get("size_in_bytes")
        if isinstance(size, int):
            link["length"] = size
        return link

    # ------------------------------------------------------------------
    # Legacy JSON feed parsing (unchanged historical behavior)
    # ------------------------------------------------------------------

    def parse_entry(self, e):
        entry = FeedParserDict()
        for src, dst in self.ITEM_FIELDS:
            if src in e:
                entry[dst] = e[src]

        if "content_text" in e:
            entry["content"] = c = FeedParserDict()
            c["value"] = e["content_text"]
            c["type"] = "text"
        elif "content_html" in e:
            entry["content"] = c = FeedParserDict()
            c["value"] = sanitize_html(
                e["content_html"], self.encoding, "application/json"
            )
            c["type"] = "html"

        if "date_published" in e:
            entry["published"] = e["date_published"]
            entry["published_parsed"] = _parse_date(e["date_published"])
        if "date_updated" in e:
            entry["updated"] = e["date_modified"]
            entry["updated_parsed"] = _parse_date(e["date_modified"])

        if "tags" in e:
            entry["category"] = e["tags"]

        if "author" in e:
            self.parse_author(e["author"], entry)

        if "attachments" in e:
            entry["enclosures"] = [self.parse_attachment(a) for a in e["attachments"]]

        return entry

    @staticmethod
    def parse_author(parent, dest):
        dest["author_detail"] = detail = FeedParserDict()
        if "name" in parent:
            dest["author"] = detail["name"] = parent["name"]
        if "url" in parent:
            if parent["url"].startswith("mailto:"):
                detail["email"] = parent["url"][7:]
            else:
                detail["href"] = parent["url"]

    @staticmethod
    def parse_attachment(attachment):
        enc = FeedParserDict()
        enc["href"] = attachment["url"]
        enc["type"] = attachment["mime_type"]
        if "size_in_bytes" in attachment:
            enc["length"] = attachment["size_in_bytes"]
        return enc
