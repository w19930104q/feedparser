# Support for RFC 6721 Atom tombstone (deleted-entry) elements
# Copyright 2010-2025 Kurt McKee <contactme@kurtmckee.org>
# Copyright 2002-2008 Mark Pilgrim
# All rights reserved.
#
# This file is a part of feedparser.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
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

from ..datetimes import _parse_date
from ..util import FeedParserDict

# RFC 6721 section 3 defines the Atom tombstone namespace.
ATOM_TOMBSTONE_NAMESPACE = "http://purl.org/atompub/tombstones/1.0"


class Namespace:
    """Support for RFC 6721 Atom tombstone ``deleted-entry`` elements.

    Tombstone support is opt-in.  It is only active when the parser's
    ``atom_tombstones`` flag is true; see :func:`feedparser.parse`.

    The element names defined by RFC 6721 contain hyphens
    (``deleted-entry``), which cannot appear in Python method names.
    ``XMLParserMixin.unknown_starttag``/``unknown_endtag`` dispatch
    ``atomtomb_*`` elements to the underscore-named handlers below.
    """

    supported_namespaces = {
        ATOM_TOMBSTONE_NAMESPACE: "atomtomb",
    }

    def _start_atomtomb_deleted_entry(self, attrs_d):
        # A nested deleted-entry is not a tombstone (RFC 6721 only allows
        # deleted-entry as a child of an Atom feed or as a document root).
        # Leave nested elements to the default (unknown-element) machinery.
        if self.intombstone:
            self.push("atomtomb_deleted_entry", 1)
            return
        self.intombstone = 1
        self.tombstonedata = FeedParserDict()
        # Keep the original ref attribute verbatim; relative URIs are *not*
        # resolved, since the ref identifies the original entry.
        self.tombstonedata["ref"] = attrs_d.get("ref", "")
        self.tombstonedata["when"] = attrs_d.get("when", "")
        # ``links`` is expected by the shared Atom link handler.
        self.tombstonedata["links"] = []
        # Track the tombstone on the element stack so that descendant
        # foreign markup can be detected and isolated.
        self.push("atomtomb_deleted_entry", 0)

    def _end_atomtomb_deleted_entry(self):
        if self.tombstonedata is None:
            # Nested deleted-entry handled by the default machinery.
            self.pop("atomtomb_deleted_entry")
            return

        ref = self.tombstonedata.get("ref", "")
        when = self.tombstonedata.get("when", "")
        when_parsed = _parse_date(when) if when else None

        # Pop the tracking element first; the tombstone data itself is kept
        # until validation decides where it goes.
        self.pop("atomtomb_deleted_entry")

        # A tombstone must carry a non-empty ref and a parseable when
        # attribute.  Invalid tombstones are quarantined in a separate
        # diagnostics list so they never pollute the feed or the entries
        # surrounding them.
        if not ref or when_parsed is None:
            diagnostic = FeedParserDict(
                reason=(
                    "deleted-entry is missing a ref attribute"
                    if not ref
                    else "deleted-entry has an invalid when attribute"
                ),
                ref=ref,
                when=when,
            )
            self.tombstone_diagnostics.append(diagnostic)
            self.tombstonedata = None
            self.intombstone = 0
            return

        self.tombstonedata["when_parsed"] = when_parsed
        # The links list is only useful when the tombstone actually links
        # somewhere; keep the output tidy otherwise.
        if not self.tombstonedata["links"]:
            del self.tombstonedata["links"]
        self.deleted_entries.append(self.tombstonedata)
        self.tombstonedata = None
        self.intombstone = 0

    def _start_atomtomb_by(self, attrs_d):
        if self.tombstonedata is None:
            # Tombstone support is disabled or this is a nested element;
            # let the default unknown-element machinery collect it.
            self.push("by", 0)
            return
        # ``by`` is an Atom Person construct. It is collected independently
        # of the generic author machinery so the tombstone dictionary only
        # exposes the RFC 6721 ``by``/``by_detail`` names.
        self.inby = 1
        self.bydata = FeedParserDict()
        self.push("by", 0)

    def _end_atomtomb_by(self):
        if self.tombstonedata is None:
            # Nested element collected by the default machinery.
            self.pop("by")
            return
        self.pop("by")
        self.inby = 0
        if self.bydata:
            self.tombstonedata["by_detail"] = FeedParserDict(self.bydata)
            if "name" in self.bydata:
                self.tombstonedata["by"] = self.bydata["name"]
        self.bydata = None

    def _start_atomtomb_source(self, attrs_d):
        if self.tombstonedata is None:
            # Nested element collected by the default machinery.
            self.push("source", 0)
            return
        # A tombstone's source is an Atom source element describing the
        # feed the deleted entry originated from.
        self.push("source", 0)
        self.intombsource = 1
        self.tombsourcedata = FeedParserDict(links=[])

    def _end_atomtomb_source(self):
        if self.tombstonedata is None:
            self.pop("source")
            return
        self.pop("source")
        self.intombsource = 0
        if not self.tombsourcedata["links"]:
            del self.tombsourcedata["links"]
        self.tombstonedata["source"] = FeedParserDict(self.tombsourcedata)
        self.tombsourcedata = None

    def _start_atomtomb_comment(self, attrs_d):
        if self.tombstonedata is None:
            # Tombstone support is disabled or this is a nested element.
            self.push("comment", 1)
            return
        # comment is an Atom Text construct, so it follows the same base URI,
        # language, and sanitization rules as entry title/summary content.
        # This mirrors _start_content(): push_content() pushes the tracking
        # element and a second push collects the actual text.
        self.hasContent = 1
        self.push_content("comment", attrs_d, "text/plain", 1)
        self.push("comment", 1)

    def _end_atomtomb_comment(self):
        if self.tombstonedata is None:
            self.pop("comment")
            return
        # Capture the Text construct metadata before it is cleared, then pop
        # the text element; pop_content() pops the tracking element and
        # applies relative-URI resolution and HTML sanitization.
        detail = FeedParserDict(self.contentparams)
        value = self.pop("comment")
        self.pop_content("comment")
        if value:
            self.tombstonedata["comment"] = value
            detail["value"] = value
            self.tombstonedata["comment_detail"] = detail

    def _start_atomtomb_link(self, attrs_d):
        if self.tombstonedata is None:
            # Tombstone support is disabled or this is a nested element.
            self.push("link", 1)
            return
        # Delegate to the shared Atom link handler so that relative URI
        # resolution and the rel/type defaults match regular entries.
        self._start_link(attrs_d)

    def _end_atomtomb_link(self):
        if self.tombstonedata is None:
            self.pop("link")
            return
        self._end_link()
