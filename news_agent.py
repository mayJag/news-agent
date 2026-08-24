import hashlib
import html
import os
import re
import smtplib
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import feedparser
import requests


FEEDS = {
    "Global News": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
    "Indian News": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "AI News": "https://news.google.com/rss/search?q=%22artificial+intelligence%22+OR+ChatGPT+OR+OpenAI+OR+Anthropic+OR+%22machine+learning%22+OR+%22AI+model%22&hl=en-IN&gl=IN&ceid=IN:en",
    "Agentic AI": "https://news.google.com/rss/search?q=%22agentic+AI%22+OR+%22AI+agents%22+OR+%22AI+agent%22+OR+%22autonomous+agents%22+OR+%22multi-agent%22&hl=en-IN&gl=IN&ceid=IN:en",
    "Sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
}

SECTION_META = {
    "Global News": {"label": "WORLD", "accent": "#2563eb"},
    "Indian News": {"label": "INDIA", "accent": "#059669"},
    "Technology": {"label": "TECH", "accent": "#7c3aed"},
    "AI News": {"label": "AI", "accent": "#0d9488"},
    "Agentic AI": {"label": "AGENTS", "accent": "#4f46e5"},
    "Sports": {"label": "SPORTS", "accent": "#ea580c"},
}

AI_TIPS = [
    "Break large tasks into smaller sub-goals when prompting an AI agent - it reduces errors compared to one giant instruction.",
    "Ask your AI assistant to show its reasoning before the final answer - it surfaces mistakes before they reach you.",
    "Use system prompts to set a persona or constraints once, instead of repeating instructions in every message.",
    "For coding tasks, give the AI the exact error message and file path - vague descriptions produce vague fixes.",
    "Agentic AI tools work best with clear success criteria - define what 'done' looks like before letting an agent run autonomously.",
    "Ask for a plan first, then approval, then execution - this catches wrong assumptions before an agent burns time on the wrong task.",
    "When comparing AI models, test on your own real examples, not benchmark scores - your use case rarely matches the benchmark.",
    "Keep a short context file (project goals, conventions, constraints) that you paste or reference at the start of every AI session.",
    "For long documents, ask the AI to summarize section-by-section rather than all at once - accuracy drops on very long single-pass summaries.",
    "Multi-agent systems fail most often at handoffs - be explicit about what each agent should pass to the next.",
    "Use low creativity/temperature settings for factual tasks and higher settings for brainstorming - one setting doesn't fit both.",
    "Version your prompts like code - small wording changes can silently change output quality.",
    "When an AI agent has tool access (browsing, code execution), review its first few actions closely - mistakes compound fast once it's autonomous.",
    "Ask 'what would make this answer wrong?' before trusting an AI's output on anything high-stakes.",
]

DEFAULT_LIMIT = int(os.environ.get("NEWS_LIMIT", "5"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "12"))
SUMMARY_TIMEOUT_SECONDS = int(os.environ.get("SUMMARY_TIMEOUT_SECONDS", "6"))
SUMMARY_MAX_WORKERS = int(os.environ.get("SUMMARY_MAX_WORKERS", "10"))
SUMMARY_MAX_CHARS = 160

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Article:
    headline: str
    publisher: str
    link: str
    published: str
    summary: str = ""


def normalize_title(title: str) -> str:
    """Create a stable comparison key for duplicate detection."""
    title = title.rsplit(" - ", 1)[0]
    title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return re.sub(r"\s+", " ", title)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def short_digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def get_daily_tip() -> str:
    day_index = datetime.now().timetuple().tm_yday
    return AI_TIPS[day_index % len(AI_TIPS)]


def format_published(entry) -> str:
    published = getattr(entry, "published", "")
    if not published:
        return "Fresh update"

    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%b %d, %H:%M")
    except (TypeError, ValueError, IndexError):
        return published


class _MetaDescriptionParser(HTMLParser):
    """Pulls og:description / description meta tags out of an article page."""

    def __init__(self):
        super().__init__()
        self.description = ""
        self.og_description = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return

        attr_dict = {key.lower(): (value or "") for key, value in attrs}
        content = attr_dict.get("content", "").strip()
        if not content:
            return

        if attr_dict.get("property", "").lower() == "og:description":
            self.og_description = content
        elif attr_dict.get("name", "").lower() == "description":
            self.description = content


def clean_summary(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"
    return text


def fetch_article_summary(url: str) -> str:
    """Best-effort fetch of a publisher's own meta description for an article."""
    try:
        response = requests.get(
            url,
            timeout=SUMMARY_TIMEOUT_SECONDS,
            headers={"User-Agent": BROWSER_USER_AGENT},
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    parser = _MetaDescriptionParser()
    try:
        parser.feed(response.text[:80_000])
    except Exception:
        return ""

    summary = parser.og_description or parser.description
    return clean_summary(summary) if summary else ""


def enrich_with_summaries(news_data: dict[str, list[Article]]) -> dict[str, list[Article]]:
    targets = [
        (category, index)
        for category, articles in news_data.items()
        for index in range(len(articles))
    ]
    if not targets:
        return news_data

    enriched = {category: list(articles) for category, articles in news_data.items()}

    with ThreadPoolExecutor(max_workers=SUMMARY_MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_article_summary, enriched[category][index].link): (category, index)
            for category, index in targets
        }
        for future, (category, index) in futures.items():
            try:
                summary = future.result()
            except Exception:
                summary = ""
            if summary:
                enriched[category][index] = replace(enriched[category][index], summary=summary)

    return enriched


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


def render_hero_card(article: Article, accent: str) -> str:
    headline = html.escape(article.headline)
    publisher = html.escape(article.publisher)
    published = html.escape(article.published)
    link = html.escape(article.link, quote=True)

    summary_html = (
        f'<div style="margin-top: 10px; color: #475569; font-size: 14px; line-height: 1.55;">{html.escape(article.summary)}</div>'
        if article.summary
        else ""
    )

    return f"""
      <tr>
        <td style="padding: 0 0 12px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #ffffff; border: 1px solid #e5e7eb; border-left: 4px solid {accent}; border-radius: 14px;">
            <tr>
              <td style="padding: 20px 20px 18px 18px;">
                <div style="display: inline-block; padding: 4px 10px; border-radius: 999px; background: #f8fafc; border: 1px solid #e5e7eb; color: {accent}; font-size: 11px; font-weight: 800; letter-spacing: 0.6px;">TOP STORY</div>
                <div style="margin-top: 10px;">
                  <a href="{link}" style="color: #0f172a; text-decoration: none; font-size: 19px; line-height: 1.35; font-weight: 800;">{headline}</a>
                </div>
                {summary_html}
                <div style="padding-top: 14px;">
                  <span style="display: inline-block; color: {accent}; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 700;">{publisher}</span>
                  <span style="display: inline-block; color: #94a3b8; font-size: 12px; font-weight: 600; padding-left: 8px;">{published}</span>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    """


def render_compact_card(article: Article, index: int, accent: str) -> str:
    headline = html.escape(article.headline)
    publisher = html.escape(article.publisher)
    published = html.escape(article.published)
    link = html.escape(article.link, quote=True)

    summary_html = (
        f'<div style="margin-top: 6px; color: #64748b; font-size: 13px; line-height: 1.5;">{html.escape(article.summary)}</div>'
        if article.summary
        else ""
    )

    return f"""
      <tr>
        <td style="padding: 0 0 10px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;">
            <tr>
              <td style="padding: 14px 16px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td width="26" valign="top">
                      <div style="width: 22px; height: 22px; border-radius: 999px; background: {accent}; color: #ffffff; text-align: center; font-size: 11px; line-height: 22px; font-weight: 700;">{index}</div>
                    </td>
                    <td valign="top">
                      <a href="{link}" style="color: #111827; text-decoration: none; font-size: 14.5px; line-height: 1.4; font-weight: 700;">{headline}</a>
                      {summary_html}
                      <div style="padding-top: 8px;">
                        <span style="color: {accent}; font-size: 11px; font-weight: 700;">{publisher}</span>
                        <span style="color: #94a3b8; font-size: 11px; font-weight: 600; padding-left: 6px;">· {published}</span>
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
    anchor_id = slugify(category)
    count_text = f"{len(articles)} stor{'y' if len(articles) == 1 else 'ies'}"

    if not articles:
        body = render_empty_state()
    else:
        hero, rest = articles[0], articles[1:]
        body = render_hero_card(hero, accent) + "\n".join(
            render_compact_card(article, index, accent)
            for index, article in enumerate(rest, start=2)
        )

    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 34px;" id="{anchor_id}">
        <tr>
          <td style="padding: 0 0 14px 0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td valign="bottom">
                  <div style="font-size: 11px; letter-spacing: 1.4px; color: {accent}; font-weight: 800;">{label}</div>
                  <h2 style="margin: 4px 0 0 0; color: #111827; font-size: 22px; line-height: 1.25; font-weight: 800;">{category_text}</h2>
                </td>
                <td align="right" valign="bottom">
                  <span style="display: inline-block; color: #64748b; background: #f1f5f9; border-radius: 999px; padding: 4px 10px; font-size: 11px; font-weight: 700;">{count_text}</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        {body}
      </table>
    """


def render_tip_section(tip: str) -> str:
    tip_text = html.escape(tip)

    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom: 34px;" id="ai-tip">
        <tr>
          <td style="padding: 0 0 14px 0;">
            <div style="font-size: 11px; letter-spacing: 1.4px; color: #0f766e; font-weight: 800;">AI TIP OF THE DAY</div>
          </td>
        </tr>
        <tr>
          <td style="padding: 18px; background: #ecfeff; border: 1px solid #a5f3fc; border-radius: 14px; color: #0f172a; font-size: 15px; line-height: 1.6; font-weight: 600;">
            {tip_text}
          </td>
        </tr>
      </table>
    """


def render_quick_nav() -> str:
    pills = "".join(
        f'<a href="#{slugify(category)}" style="display: inline-block; margin: 0 6px 8px 0; padding: 6px 14px; border-radius: 999px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); color: #e2e8f0; font-size: 12px; font-weight: 700; text-decoration: none;">{html.escape(SECTION_META.get(category, {}).get("label", category))}</a>'
        for category in FEEDS
    )
    pills += '<a href="#ai-tip" style="display: inline-block; margin: 0 6px 8px 0; padding: 6px 14px; border-radius: 999px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); color: #5eead4; font-size: 12px; font-weight: 700; text-decoration: none;">TIP</a>'
    return f'<div style="padding-top: 16px;">{pills}</div>'


def generate_html_email(news_data: dict[str, list[Article]]) -> str:
    date_str = html.escape(datetime.now().strftime("%A, %B %d"))
    total_articles = sum(len(articles) for articles in news_data.values())

    sections = "\n".join(
        render_section(category, news_data.get(category, []))
        for category in FEEDS
    )
    sections += render_tip_section(get_daily_tip())

    quick_nav = render_quick_nav()

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
            <td style="background-color: #0f172a; background-image: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 34px 30px 26px 30px;">
              <div style="color: #93c5fd; font-size: 12px; letter-spacing: 2px; font-weight: 800;">MORNING BRIEFING</div>
              <h1 style="margin: 8px 0 10px 0; color: #ffffff; font-size: 34px; line-height: 1.1; font-weight: 800;">The Daily Digest</h1>
              <div style="color: #cbd5e1; font-size: 15px; line-height: 1.5;">{date_str} · {total_articles} selected stories from Google News</div>
              {quick_nav}
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
            if article.summary:
                lines.append(f"   {article.summary}")
            lines.append(f"   {article.link}")
        lines.append("")

    lines.append("AI TIP OF THE DAY")
    lines.append(get_daily_tip())
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

    print(f"Fetching article summaries for {article_count} article(s)...")
    news_data = enrich_with_summaries(news_data)
    summarized_count = sum(
        1 for articles in news_data.values() for article in articles if article.summary
    )
    print(f"Got summaries for {summarized_count}/{article_count} article(s).")

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
