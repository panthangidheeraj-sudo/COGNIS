"""News items are published only with a real article URL, a meaningful headline and a genuine publication date; every rejection keeps its reason."""
from __future__ import annotations

from datetime import date, timedelta

from app.connectors import news_discovery
from app.connectors import news_validation as nv
from app.connectors.newsroom import parse_feed
from app.extraction.html import parse_html

TODAY = date(2026, 11, 4)
GOOD = {"title": "Autobjørn signerer rammeavtale med Statens vegvesen", "url": "https://www.autobjorn.no/nyheter/rammeavtale-statens-vegvesen", "day": "2026-10-20",
        "date_source": "datePublished", "today": TODAY, "max_age_days": 365, "listing_url": "https://www.autobjorn.no/nyheter"}


def check(**over):  # noqa: ANN003, ANN201
    return nv.validate_item(**{**GOOD, **over})


def test_a_real_dated_article_passes() -> None:
    assert check().ok


def test_listing_section_tag_and_pagination_pages_are_not_articles() -> None:
    for url in ("https://www.autobjorn.no/nyheter", "https://www.autobjorn.no/nyheter/", "https://www.autobjorn.no/en/news", "https://www.autobjorn.no/tag/elbil",
                "https://www.autobjorn.no/nyheter/page/2", "https://www.autobjorn.no/arkiv", "https://www.autobjorn.no/category/pressemeldinger"):
        v = check(url=url, listing_url="https://elsewhere.example/")
        assert not v.ok and v.reason, url


def test_the_listing_page_itself_is_not_the_article_url() -> None:
    v = check(url="https://autobjorn.no/nyheter/oversikt-2026", listing_url="https://www.autobjorn.no/nyheter/oversikt-2026/")
    assert not v.ok and "listing page" in v.reason


def test_bare_domains_missing_links_navigation_product_and_file_urls_are_rejected() -> None:
    cases = {"https://www.autobjorn.no": "bare domain", "https://www.autobjorn.no/": "bare domain", None: "no article link", "": "no article link",
             "https://www.autobjorn.no/produkter": "product", "https://www.autobjorn.no/tjenester/": "product", "https://www.autobjorn.no/kontakt": "navigation",
             "https://www.autobjorn.no/files/rapport-2026.pdf": "file", "https://www.facebook.com/sharer/sharer.php?u=x": "share", "mailto:post@autobjorn.no": "absolute"}
    for url, word in cases.items():
        v = check(url=url)
        assert not v.ok and word in v.reason, (url, v.reason)


def test_navigation_text_and_one_word_titles_are_not_headlines() -> None:
    for title in ("Les mer", "Nyheter", "Alle nyheter", "Autobjørn", "Se alle nyheter her", "14. august 2026"):
        assert not check(title=title).ok, title


def test_only_publication_dates_count() -> None:
    for source in ("dateModified", "dateCreated", "updated", "lastBuildDate", "retrieved_at"):
        v = check(date_source=source)
        assert not v.ok and "not the publication date" in v.reason, source
    assert not check(day=None).ok and not check(day="not-a-date").ok and not check(day="2026-13-45").ok


def test_future_and_stale_dates_are_rejected() -> None:
    assert "future" in check(day=(TODAY + timedelta(days=30)).isoformat()).reason
    assert "older than" in check(day="2019-01-01").reason


def test_rss_updated_is_not_used_as_the_publication_date() -> None:
    xml = ('<rss version="2.0"><channel><item><title>Autobjørn åpner nytt servicesenter i Stavanger</title><link>https://www.autobjorn.no/nyheter/stavanger</link>'
           "<updated>2026-10-30T10:00:00Z</updated></item>"
           '<item><title>Autobjørn vinner pris for beste verksted</title><link>https://www.autobjorn.no/nyheter/pris</link><pubDate>Mon, 19 Oct 2026 08:00:00 +0000</pubDate></item></channel></rss>')
    rows = parse_feed(xml, "https://www.autobjorn.no/feed.xml")
    assert rows[0][2] is None and rows[1][2] == "2026-10-19"


def _doc(html: str, url: str = "https://e24.no/avtale-slug"):  # noqa: ANN202
    return parse_html(url, url, html, content_sha256="x", retrieved_at="2026-11-01T08:00:00Z")


BODY = "Autobjørn AS har inngått en avtale som gjelder leveranse av tjenestebiler i fire år, opplyser selskapet. " * 3


def test_press_page_with_only_a_modified_date_is_not_an_article_with_a_date() -> None:
    html = ('<html><head><title>Autobjørn vinner kontrakt med Forsvaret</title><script type="application/ld+json">{"@type":"NewsArticle",'
            '"headline":"Autobjørn vinner kontrakt med Forsvaret","dateModified":"2026-10-28"}</script></head><body><h1>Autobjørn vinner kontrakt med Forsvaret</h1><p>' + BODY + "</p></body></html>")
    art, why = news_discovery.read_article(_doc(html))
    assert art is None and "modification date" in why


def test_press_page_with_dateCreated_only_is_not_dated() -> None:
    html = ('<html><head><title>Autobjørn vinner kontrakt med Forsvaret</title><script type="application/ld+json">{"@type":"NewsArticle",'
            '"headline":"Autobjørn vinner kontrakt med Forsvaret","dateCreated":"2026-10-28"}</script></head><body><h1>Autobjørn vinner kontrakt med Forsvaret</h1><p>' + BODY + "</p></body></html>")
    art, why = news_discovery.read_article(_doc(html))
    assert art is None and "modification date" in why or "no publication date" in why


def test_a_bare_time_element_does_not_date_an_article() -> None:
    html = ('<html><head><title>Autobjørn vinner kontrakt med Forsvaret</title></head><body><h1>Autobjørn vinner kontrakt med Forsvaret</h1>'
            '<time datetime="2026-10-28">28. oktober</time><p>' + BODY + "</p></body></html>")
    art, why = news_discovery.read_article(_doc(html))
    assert art is None and "no publication date" in why


def test_article_text_is_required_for_press_coverage() -> None:
    assert nv.body_problem(["Kort."]) and "no readable article text" in nv.body_problem(["Kort."])
    assert nv.body_problem([BODY]) is None


def test_modified_time_elements_in_a_listing_are_not_publication_dates() -> None:
    html = ('<html><body><article><time itemprop="dateModified" datetime="2026-10-30">30. oktober 2026</time><h2><a href="/nyheter/a-b-c">Autobjørn åpner nytt servicesenter</a></h2>'
            "<p>Tekst om saken som er lang nok til å regnes som et sammendrag av nyheten.</p></article></body></html>")
    assert _doc(html, "https://www.autobjorn.no/nyheter").items == []
