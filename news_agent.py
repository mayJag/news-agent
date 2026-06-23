import feedparser
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# Define the RSS feeds we want to fetch
FEEDS = {
    "Global News": "https://news.google.com/rss",
    "Indian News": "https://news.google.com/rss/headlines/section/geo/IN",
    "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY",
    "Sports": "https://news.google.com/rss/headlines/section/topic/SPORTS"
}

def get_news(feed_url, limit=5):
    """Fetches the top 'limit' news articles from the RSS feed."""
    feed = feedparser.parse(feed_url)
    entries = []
    for entry in feed.entries[:limit]:
        entries.append(f"<li><a href='{entry.link}' style='text-decoration: none; color: #1a0dab;'>{entry.title}</a></li>")
    return "\n".join(entries)

def generate_html_email():
    """Generates the HTML content for the email."""
    html_content = """
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: auto;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px;">
            <h2 style="color: #202124; margin-top: 0;">Your Daily Morning Digest</h2>
            <p>Good morning! Here are the top news headlines for today:</p>
        </div>
    """
    
    for category, url in FEEDS.items():
        html_content += f"<h3 style='color: #d93025; border-bottom: 2px solid #f1f3f4; padding-bottom: 5px; margin-top: 25px;'>{category}</h3>\n"
        html_content += "<ul style='padding-left: 20px;'>\n"
        html_content += get_news(url)
        html_content += "</ul>\n"
        
    html_content += """
        <hr style="border: 0; border-top: 1px solid #eee; margin-top: 30px;">
        <p style="font-size: 12px; color: #777; text-align: center;">Generated automatically by your News Agent.</p>
      </body>
    </html>
    """
    return html_content

def send_email(html_content):
    """Sends the HTML email using Gmail SMTP."""
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    receiver_email = os.environ.get("RECEIVER_EMAIL")
    
    if not all([sender_email, sender_password, receiver_email]):
        print("Error: Missing email credentials in environment variables.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Daily News Digest - {datetime.now().strftime('%d %b %Y')}"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    
    # Attach HTML content
    part = MIMEText(html_content, "html")
    msg.attach(part)
    
    try:
        # Connect to Gmail SMTP server
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        print(f"Email sent successfully to {receiver_email}!")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    print("Fetching news from Google News RSS feeds...")
    html_email = generate_html_email()
    print("Sending email digest...")
    send_email(html_email)
    print("Agent execution complete.")
