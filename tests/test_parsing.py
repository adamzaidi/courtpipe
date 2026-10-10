"""Parsing helpers from extract and enrich. Fixture text only; no HTTP."""

from __future__ import annotations

from etl.enrich_helpers import (
    _best_citation_from_citations_list,
    _cluster_id_from_url,
    _strip_html as enrich_strip_html,
    detect_per_curiam,
    header_from_text_body,
    infer_court_from_header,
    normalize_court_name,
    outcome_from_text,
    pick_citation_from_header,
)
from etl.extract import (
    _build_head_tail_snippets,
    _extract_opinion_id_from_search_hit,
    _infer_state_from_court_name,
    _normalize_api_url,
    _normalize_url,
    _pick_citation,
    _sanitize_for_csv,
    _split_plain_text,
    _strip_html as extract_strip_html,
)


OPINION_HEADER = """UNITED STATES COURT OF APPEALS FOR THE NINTH CIRCUIT

Example Corp. v. Sample Holdings, 410 F.3d 256 (9th Cir. 2005)

Per Curiam.
"""


def test_split_plain_text_url_versus_inline():
    assert _split_plain_text(None) == ("", "")
    assert _split_plain_text("   ") == ("", "")
    assert _split_plain_text("https://www.courtlistener.com/download/1/") == (
        "https://www.courtlistener.com/download/1/",
        "",
    )
    assert _split_plain_text("/download/1/") == ("https://www.courtlistener.com/download/1/", "")
    assert _split_plain_text("The judgment is affirmed.") == ("", "The judgment is affirmed.")


def test_normalize_urls():
    assert _normalize_url(None) == ""
    assert _normalize_url("  ") == ""
    assert _normalize_url("12345") == "12345"
    assert _normalize_url("/api/rest/v4/opinions/9") == "https://www.courtlistener.com/api/rest/v4/opinions/9/"
    assert _normalize_url("https://www.courtlistener.com/api/rest/v4/opinions/9?format=json") == (
        "https://www.courtlistener.com/api/rest/v4/opinions/9/"
    )
    assert _normalize_api_url("42", "opinions") == "https://www.courtlistener.com/api/rest/v4/opinions/42/"
    assert _normalize_api_url("/api/rest/v4/clusters/7", "clusters") == (
        "https://www.courtlistener.com/api/rest/v4/clusters/7/"
    )


def test_pick_citation_prefers_a_cite_field():
    cites = [
        {"volume": "1", "reporter": "F.3d", "page": "1", "type": 1},
        {"cite": "410 F.3d 256", "type": 4},
    ]
    assert _pick_citation(cites) == "410 F.3d 256"
    assert _pick_citation("410 F.3d 256") == "410 F.3d 256"
    assert _pick_citation(None) == ""
    assert _pick_citation([{"volume": "410", "reporter": "F.3d", "page": "256", "type": "2"}]) == "410 F.3d 256"


def test_infer_state_from_court_name():
    assert _infer_state_from_court_name("") == ""
    assert _infer_state_from_court_name("U.S. Court of Appeals for the Ninth Circuit") == "Federal"
    assert _infer_state_from_court_name("Supreme Court of New York") == "New York"
    assert _infer_state_from_court_name("Mystery Tribunal") == ""


def test_html_strip_and_csv_sanitize_and_snippets():
    html = "<p>Hello &amp; Co.</p><script>bad()</script><style>x{}</style>"
    assert "bad" not in extract_strip_html(html)
    assert "Hello" in extract_strip_html(html)
    assert "<" not in extract_strip_html(html)

    stripped = enrich_strip_html(html)
    assert "Hello & Co." in stripped
    assert "bad" not in stripped

    assert _sanitize_for_csv("a\n\tb   c") == "a b c"
    head, tail, default = _build_head_tail_snippets("short opinion text")
    assert head == tail == default == "short opinion text"


def test_extract_opinion_id_from_search_hit():
    assert _extract_opinion_id_from_search_hit({"opinions": [12345]}) == 12345
    assert _extract_opinion_id_from_search_hit({"opinions": ["https://www.courtlistener.com/opinion/99/"]}) == 99
    assert _extract_opinion_id_from_search_hit({"absolute_url": "/opinion/77/"}) == 77
    assert _extract_opinion_id_from_search_hit({"id": "15"}) == 15
    assert _extract_opinion_id_from_search_hit({}) is None


def test_header_parsing_and_per_curiam():
    assert _cluster_id_from_url("https://www.courtlistener.com/api/rest/v4/clusters/12345/") == "12345"
    assert _cluster_id_from_url("https://example.com/nope") == ""

    name = normalize_court_name("United States Court of Appeals for the Ninth Circuit")
    assert name.startswith("U.S. Court of Appeals")

    found = infer_court_from_header(OPINION_HEADER)
    assert "COURT OF APPEALS" in found.upper()
    assert header_from_text_body("a\nb\nc").count("\n") == 2
    assert pick_citation_from_header(OPINION_HEADER) == "410 F.3d 256"
    assert detect_per_curiam(OPINION_HEADER) == 1
    assert detect_per_curiam("signed opinion") == 0


def test_outcome_from_text_uses_the_tail():
    assert outcome_from_text("The judgment is reversed.") == ("Loss", 0)
    assert outcome_from_text("The judgment is affirmed.") == ("Win", 1)
    assert outcome_from_text("The judgment is affirmed in part and reversed in part.") == ("Mixed", 2)
    assert outcome_from_text("The case is remanded.") == ("Partial", 3)
    assert outcome_from_text("The appeal is dismissed.") == ("Other", 5)
    assert outcome_from_text("The order is vacated.") == ("Other", 5)
    assert outcome_from_text("") == ("Other", 5)

    # An affirm more than 200 lines above the disposition is outside the tail window.
    lines = ["The panel affirmed the unrelated motion."]
    lines.extend(["background"] * 200)
    lines.append("The judgment is reversed.")
    assert outcome_from_text("\n".join(lines)) == ("Loss", 0)


def test_best_citation_prefers_official_reporter():
    cites = [
        {"type": "parallel", "cite": "2005 WL 1"},
        {"type": "official", "cite": "410 F.3d 256"},
    ]
    assert _best_citation_from_citations_list(cites) == "410 F.3d 256"
    assert _best_citation_from_citations_list("nope") == ""
    assert _best_citation_from_citations_list([{"type": "other", "cite": "slip op."}]) == "slip op."
