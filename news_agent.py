import hashlib
import html
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

import feedparser
import requests


FEEDS = {
    "Global News": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
    "Indian News": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "Sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
}

SECTION_META = {
    "Global News": {"label": "WORLD", "accent": "#2563eb"},
    "Indian News": {"label": "INDIA", "accent": "#059669"},
    "Technology": {"label": "TECH", "accent": "#7c3aed"},
    "Sports": {"label": "SPORTS", "accent": "#ea580c"},
}

DEFAULT_LIMIT = int(os.environ.get("NEWS_LIMIT", "5"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "12"))


@dataclass(frozen=True)
class Article:
    headline: str
    publisher: str
    link: str
    published: str


def normalize_title(title: str) -> str:
    """Create a stable comparison key for duplicate detection."""
    title = title.rsplit(" - ", 1)[0]
    title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return re.sub(r"\s+", " ", title)


def short_digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def format_published(entry) -> str:
    published = getattr(entry, "published", "")
    if not published:
        return "Fresh update"

    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%b %d, %H:%M")
    except (TypeError, ValueError, IndexError):
        return published


def fetch_articles(category: str, feed_url: str, seen_titles: set[str], limit: int) -> list[Article]:
    response = requests.get(
        feed_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "DailyNewsAgent/1.0 (+https://github.com/mayJag/news-agent)"},
    )
    response.raise_for_status()

    feed = feedparser.parse(response.text)
    if getattr(feed, "bozo", False):
        print(f"Warning: RSS parser reported malformed feed for {category}.")

    articles = []
    for entry in feed.entries:
        raw_title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not raw_title or not link:
            continue

        title_parts = raw_title.rsplit(" - ", 1)
        headline = title_parts[0].strip()
        publisher = title_parts[1].strip() if len(title_parts) > 1 else "Google News"
        dedupe_key = normalize_title(headline)

        if not dedupe_key or dedupe_key in seen_titles:
            continue

        seen_titles.add(dedupe_key)
        articles.append(
            Article(
                headline=headline,
                publisher=publisher,
                link=link,
                published=format_published(entry),
            )
        )

        if len(articles) >= limit:
            break

    print(f"{category}: {len(articles)} articles")
    return articles


def fetch_all_news(limit: int = DEFAULT_LIMIT) -> dict[str, list[Article]]:
    news = {}
    seen_titles: set[str] = set()

    for category, url in FEEDS.items():
        try:
            news[category] = fetch_articles(category, url, seen_titles, limit)
        except requests.RequestException as exc:
            print(f"Warning: failed to fetch {category}: {exc}")
            news[category] = []

    return news


def render_article_card(article: Article, index: int, accent: str) -> str:
    headline = html.escape(article.headline)
    publisher = html.escape(article.publisher)
    published = html.escape(article.published)
    link = html.escape(article.link, quote=True)

    return f"""
      <tr>
        <td style="padding: 0 0 14px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px;">
            <tr>
              <td style="padding: 18px 18px 16px 18px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="34" valign="top">
                      <div style="width: 28px; height: 28px; border-radius: 999px; background: {accent}; color: #ffffff; text-align: center; font-size: 13px; line-height: 28px; font-weight: 700;">{index}</div>
                    </td>
                    <td valign="top">
                      <a href="{link}" style="color: #111827; text-decoration: none; font-size: 16px; line-height: 1.45; font-weight: 700;">{headline}</a>
                      <div style="padding-top: 12px;">
                        <span style="display: inline-block; color: {accent}; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 700;">{publisher}</span>
                        <span style="display: inline-block; color: #6b7280; font-size: 12px; font-weight: 600; padding-left: 8px;">{published}</span>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    """


def render_empty_state() -> str:
    return """
      <tr>
        <td style="padding: 18px; background: #ffffff; border: 1px dashed #d1d5db; border-radius: 14px; color: #6b7280; font-size: 14px;">
          No fresh stories available in this section right now.
        </td>
      </tr>
    """


def render_section(category: str, articles: list[Article]) -> str:
    meta = SECTION_META.get(category, {"label": "NEWS", "accent": "#111827"})
    label = html.escape(meta["label"])
    accent = meta["accent"]
    category_text = html.escape(category)

    article_rows = "\n".join(
        render_article_card(article, index, accent)
        for index, article in enumerate(articles, start=1)
    ) or render_empty_state()

    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 34px;">
        <tr>
          <td style="padding: 0 0 14px 0;">
            <div style="font-size: 11px; letter-spacing: 1.4px; color: {accent}; font-weight: 800;">{label}</div>
            <h2 style="margin: 4px 0 0 0; color: #111827; font-size: 22px; line-height: 1.25; font-weight: 800;">{category_text}</h2>
          </td>
        </tr>
        {article_rows}
      </table>
    """


def generate_html_email(news_data: dict[str, list[Article]]) -> str:
    date_str = html.escape(datetime.now().strftime("%A, %B %d"))
    total_articles = sum(len(articles) for articles in news_data.values())

    sections = "\n".join(
        render_section(category, news_data.get(category, []))
        for category in FEEDS
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>The Daily Digest</title>
</head>
<body style="margin: 0; padding: 0; background: #eef2f7; color: #111827; font-family: Arial, Helvetica, sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #eef2f7; padding: 24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; background: #f8fafc; border-radius: 20px; overflow: hidden; border: 1px solid #dbe3ef;">
          <tr>
            <td style="background: #111827; padding: 34px 30px 30px 30px;">
              <div style="color: #93c5fd; font-size: 12px; letter-spacing: 2px; font-weight: 800;">MORNING BRIEFING</div>
              <h1 style="margin: 8px 0 10px 0; color: #ffffff; font-size: 34px; line-height: 1.1; font-weight: 800;">The Daily Digest</h1>
              <div style="color: #d1d5db; font-size: 15px; line-height: 1.5;">{date_str} · {total_articles} selected stories from Google News</div>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 24px 6px 24px;">
              {sections}
            </td>
          </tr>
          <tr>
            <td style="padding: 24px 28px 30px 28px; background: #e5e7eb; text-align: center;">
              <div style="color: #374151; font-size: 14px; font-weight: 700;">Generated by your News Agent</div>
              <div style="color: #6b7280; font-size: 12px; margin-top: 8px;">You are receiving this because you are subscribed to the morning digest.</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def generate_text_email(news_data: dict[str, list[Article]]) -> str:
    lines = [
        "The Daily Digest",
        datetime.now().strftime("%A, %B %d"),
        "",
    ]

    for category in FEEDS:
        lines.append(category.upper())
        articles = news_data.get(category, [])
        if not articles:
            lines.append("- No fresh stories available.")
        for index, article in enumerate(articles, start=1):
            lines.append(f"{index}. {article.headline} ({article.publisher})")
            lines.append(f"   {article.link}")
        lines.append("")

    lines.append("Generated by your News Agent")
    return "\n".join(lines)


def get_recipients() -> list[str]:
    receiver_emails_str = os.environ.get("RECEIVER_EMAIL", "")
    recipients = [email.strip() for email in receiver_emails_str.split(",") if email.strip()]
    if not recipients:
        raise RuntimeError("RECEIVER_EMAIL is missing or empty.")
    return recipients


def send_email(html_content: str, text_content: str) -> None:
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    if not sender_email or not sender_password:
        raise RuntimeError("SENDER_EMAIL and SENDER_PASSWORD must be set.")

    recipients = get_recipients()
    subject = f"Daily News Digest - {datetime.now().strftime('%d %b %Y')}"

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender_email, sender_password)

        for receiver_email in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = sender_email
            msg["To"] = receiver_email
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            server.sendmail(sender_email, receiver_email, msg.as_string())
            print(f"Email sent to {receiver_email}")

    print(f"Sent digest to {len(recipients)} recipient(s).")


def main() -> None:
    print("Fetching news from Google News RSS feeds...")
    news_data = fetch_all_news()
    article_count = sum(len(articles) for articles in news_data.values())
    if article_count == 0:
        raise RuntimeError("No articles fetched from any feed.")

    print(f"Rendering digest with {article_count} article(s)...")
    html_email = generate_html_email(news_data)
    text_email = generate_text_email(news_data)
    print(f"Digest id: {short_digest(text_email)}")

    print("Sending email digest...")
    send_email(html_email, text_email)
    print("Agent execution complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Agent failed: {exc}", file=sys.stderr)
        sys.exit(1)
