import feedparser
import smtplib
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

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
        entries.append(
            f"<li style='margin-bottom: 12px; padding: 12px 15px; background-color: #ffffff; border-radius: 8px; border-left: 4px solid #2a5298; box-shadow: 0 2px 4px rgba(0,0,0,0.02);'>"
            f"<a href='{entry.link}' style='text-decoration: none; color: #2c3e50; font-weight: 500; display: block; font-size: 15px;'>{entry.title}</a>"
            f"</li>"
        )
    return "\n".join(entries)

def generate_html_email():
    """Generates the HTML content for the email."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 650px; margin: 0 auto; padding: 20px; background-color: #f4f7f6;">
      <div style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 35px 20px; text-align: center; color: white;">
            <h1 style="margin: 0; font-size: 28px; font-weight: 600; letter-spacing: 1px;">🌍 Daily News Digest</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Your morning briefing is here</p>
        </div>
        
        <!-- Content -->
        <div style="padding: 30px 20px; background-color: #fbfcfd;">
    """
    
    icons = {
        "Global News": "🌐",
        "Indian News": "🇮🇳",
        "Technology": "💻",
        "Sports": "🏅"
    }
    
    for category, url in FEEDS.items():
        icon = icons.get(category, "📰")
        html_content += f"""
          <div style="margin-bottom: 35px;">
            <h2 style="color: #1e3c72; border-bottom: 2px solid #eef2f5; padding-bottom: 10px; margin-top: 0; font-size: 20px;">
              <span style="margin-right: 8px;">{icon}</span>{category}
            </h2>
            <ul style="list-style-type: none; padding-left: 0; margin-top: 15px;">
        """
        html_content += get_news(url)
        html_content += """
            </ul>
          </div>
        """
        
    html_content += """
        </div>
        
        <!-- Footer -->
        <div style="background-color: #f8f9fa; padding: 25px 20px; text-align: center; border-top: 1px solid #eef2f5;">
            <p style="margin: 0; font-size: 13px; color: #888;">Generated automatically by your News Agent 🤖</p>
        </div>
      </div>
    </body>
    </html>
    """
    return html_content

def send_email(html_content):
    """Sends the HTML email using Gmail SMTP to multiple recipients."""
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    receiver_emails_str = os.environ.get("RECEIVER_EMAIL")
    
    if not all([sender_email, sender_password, receiver_emails_str]):
        print("Error: Missing email credentials in environment variables.")
        return

    # Split the comma-separated string into a list of emails
    receiver_emails = [email.strip() for email in receiver_emails_str.split(',')]

    try:
        # Connect to Gmail SMTP server
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender_email, sender_password)
        
        # Send individual emails to each recipient so they don't see each other's addresses
        for receiver_email in receiver_emails:
            if not receiver_email:
                continue
                
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Daily News Digest - {datetime.now().strftime('%d %b %Y')}"
            msg["From"] = sender_email
            msg["To"] = receiver_email
            
            # Attach HTML content
            part = MIMEText(html_content, "html")
            msg.attach(part)
            
            server.sendmail(sender_email, receiver_email, msg.as_string())
            print(f"Email sent successfully to {receiver_email}!")
            
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")

def wait_until_target_time(target_hour, target_minute):
    """Pauses execution until the exact target time in IST."""
    # IST is UTC + 5:30
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    if now >= target:
        print(f"Target time {target.strftime('%H:%M:%S')} IST has already passed. Executing immediately.")
        return
        
    wait_seconds = (target - now).total_seconds()
    print(f"Waiting for {wait_seconds:.0f} seconds until exactly {target.strftime('%H:%M:%S')} IST...")
    time.sleep(wait_seconds)

if __name__ == "__main__":
    # Wait until exactly 9:00 AM IST
    wait_until_target_time(9, 0)
    
    print("Fetching news from Google News RSS feeds...")
    html_email = generate_html_email()
    print("Sending email digest...")
    send_email(html_email)
    print("Agent execution complete.")
