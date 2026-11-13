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
from ..urls import resolve_relative_uris
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

    def __init__(
        self,
        baseuri=None,
        baselang=None,
        encoding=None,
        normalize_json=False,
        resolve_relative_uris=None,
        sanitize_html=None,
    ):
        self.baseuri = baseuri or ""
        self.lang = baselang or None
        self.encoding = encoding or "utf-8"  # character encoding

        # ``normalize_json`` makes the JSON feed output match the shape of
        # the XML (RSS/Atom) output. It is opt-in to preserve the historical
        # JSON output exactly.
        self.normalize_json = normalize_json
        # The XML parsers default both flags to False and rely on ``api.py``
        # to assign the effective values; mirror that default here.
        self.resolve_relative_uris = bool(resolve_relative_uris)
        self.sanitize_html = bool(sanitize_html)

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

        for src, dst in self.FEED_FIELDS:
            if src in data:
                self.feeddata[dst] = data[src]

        if self.normalize_json:
            self._normalize_feed(data)
        elif "author" in data:
            self.parse_author(data["author"], self.feeddata)
        # TODO: hubs; expired has no RSS equivalent

        self.entries = [self.parse_entry(e) for e in data["items"]]

    # ------------------------------------------------------------------
    # Normalized feed/entry parsing (JSON Feed 1 and 1.1)
    # ------------------------------------------------------------------

    def _normalize_feed(self, data):
        """Populate feed-level fields with the same shape as XML feeds."""

        feed = self.feeddata

        authors = self._parse_authors(data)
        # An explicitly present (even empty) ``authors``/``author`` value
        # is recorded as-is; entries only inherit when the feed actually
        # carries author information.
        if "authors" in data or "author" in data:
            feed["authors"] = authors
            if authors:
                self._sync_authors(feed, authors)

        links = []
        if data.get("home_page_url"):
            links.append(
                FeedParserDict(
                    rel="alternate",
                    type="text/html",
                    href=data["home_page_url"],
                )
            )
        if data.get("feed_url"):
            links.append(
                FeedParserDict(
                    rel="self",
                    type="application/feed+json",
                    href=data["feed_url"],
                )
            )
        if links:
            feed["links"] = links

    def parse_entry(self, e):
        if self.normalize_json:
            return self._normalize_entry(e)

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

    def _normalize_entry(self, e):
        """Populate entry fields with the same shape as XML entries."""

        entry = FeedParserDict()
        for src, dst in self.ITEM_FIELDS:
            if src in e:
                entry[dst] = e[src]

        # ``content`` is always a list. When both a plain text and an HTML
        # body exist, the text body is retained first and the HTML body
        # second, mirroring the order in which XML content elements occur.
        content = []
        if "content_text" in e:
            content.append(
                FeedParserDict(
                    value=e["content_text"],
                    type="text/plain",
                    base=self.baseuri,
                    language=self.lang,
                )
            )
        if "content_html" in e:
            content.append(
                FeedParserDict(
                    value=self._process_html(e["content_html"]),
                    type="text/html",
                    base=self.baseuri,
                    language=self.lang,
                )
            )
        if content:
            entry["content"] = content

        if "date_published" in e:
            entry["published"] = e["date_published"]
            entry["published_parsed"] = _parse_date(e["date_published"])
        # JSON Feed 1/1.1 names this field ``date_modified``.
        if "date_modified" in e:
            entry["updated"] = e["date_modified"]
            # ``_parse_date`` returns a 9-tuple in UTC (tm_isdst == 0).
            entry["updated_parsed"] = _parse_date(e["date_modified"])

        if "tags" in e:
            entry["tags"] = [
                FeedParserDict(term=tag, scheme=None, label=None)
                for tag in e["tags"]
                if tag
            ]

        # Authors: the entry's own authors take precedence. An entry without
        # an ``authors``/``author`` field inherits the feed's authors; an
        # explicitly empty list does not inherit anything, and a feed without
        # authors means the entry gains no ``authors`` field either (matching
        # the XML parsers, which omit the key entirely).
        if "authors" in e or "author" in e:
            authors = self._parse_authors(e)
            entry["authors"] = authors
            if authors:
                self._sync_authors(entry, authors)
        else:
            feed_authors = self.feeddata.get("authors")
            if feed_authors:
                # Deep-copy so later mutations of an entry can never leak
                # back into the feed data or into sibling entries.
                entry["authors"] = copy.deepcopy(feed_authors)
                self._sync_authors(entry, entry["authors"])

        links = []
        if e.get("url"):
            links.append(
                FeedParserDict(
                    rel="alternate",
                    type="text/html",
                    href=e["url"],
                )
            )
        if "attachments" in e:
            for attachment in e["attachments"]:
                link = FeedParserDict(rel="enclosure")
                link["href"] = attachment["url"]
                link["type"] = attachment["mime_type"]
                if "size_in_bytes" in attachment:
                    # XML enclosure lengths are strings.
                    link["length"] = str(attachment["size_in_bytes"])
                links.append(link)
        if links:
            entry["links"] = links

        return entry

    def _process_html(self, html):
        """Apply the relative-URI and sanitization settings of this parse."""

        if self.resolve_relative_uris and self.baseuri:
            html = resolve_relative_uris(html, self.baseuri, self.encoding, "text/html")
        if self.sanitize_html:
            html = sanitize_html(html, self.encoding, "text/html")
        return html

    @staticmethod
    def _parse_authors(parent):
        """Normalize JSON Feed authors into a list of author detail dicts.

        JSON Feed 1.1 uses an ``authors`` list; JSON Feed 1 uses a single
        ``author`` object. The latter is treated as a one-element list.
        """

        raw_authors = parent.get("authors")
        if raw_authors is None and "author" in parent:
            raw_authors = [parent["author"]]
        if not raw_authors:
            return []

        authors = []
        for raw in raw_authors:
            if not isinstance(raw, dict):
                continue
            detail = FeedParserDict()
            if raw.get("name"):
                detail["name"] = raw["name"]
            if raw.get("url"):
                if raw["url"].startswith("mailto:"):
                    detail["email"] = raw["url"][7:]
                else:
                    detail["href"] = raw["url"]
            if detail:
                authors.append(detail)
        return authors

    @staticmethod
    def _sync_authors(context, authors):
        """Set the legacy singular ``author``/``author_detail`` fields."""

        context["author_detail"] = copy.deepcopy(authors[-1])
        last = authors[-1]
        if "name" in last:
            context["author"] = last["name"]
        elif "email" in last:
            context["author"] = last["email"]

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
