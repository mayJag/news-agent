import feedparser
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from email.utils import parsedate_to_datetime

# Define the RSS feeds we want to fetch
FEEDS = {
    "Global News": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
    "Indian News": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "Sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en"
}

def get_news(feed_url, limit=5):
    """Fetches the top 'limit' news articles from the RSS feed."""
    feed = feedparser.parse(feed_url)
    entries_html = []
    
    for entry in feed.entries[:limit]:
        # Extract publisher from Google News title format "Headline - Publisher"
        title_parts = entry.title.rsplit(' - ', 1)
        headline = title_parts[0]
        publisher = title_parts[1] if len(title_parts) > 1 else "Google News"
        
        # Parse published date if available
        time_str = ""
        if hasattr(entry, 'published'):
            try:
                dt = parsedate_to_datetime(entry.published)
                time_str = dt.strftime("%b %d, %H:%M")
            except:
                time_str = entry.published

        entries_html.append(f"""
            <div style="margin-bottom: 16px; padding: 20px; background-color: #ffffff; border-radius: 12px; border: 1px solid #eaeaea; box-shadow: 0 4px 6px rgba(0,0,0,0.02);">
                <a href="{entry.link}" style="text-decoration: none; color: #111827; font-weight: 600; font-size: 16px; line-height: 1.4; display: block; margin-bottom: 14px;">
                    {headline}
                </a>
                <div style="display: table; width: 100%; font-size: 12px;">
                    <div style="display: table-cell; vertical-align: middle;">
                        <span style="background-color: #ecfdf5; color: #059669; padding: 5px 12px; border-radius: 20px; font-weight: 500; border: 1px solid #d1fae5;">
                            {publisher}
                        </span>
                    </div>
                    <div style="display: table-cell; vertical-align: middle; text-align: right; color: #6b7280; font-weight: 500;">
                        {time_str}
                    </div>
                </div>
            </div>
        """)
    return "\n".join(entries_html)

def generate_html_email():
    """Generates the HTML content for the email."""
    date_str = datetime.now().strftime('%A, %B %d')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #374151; margin: 0; padding: 0; background-color: #f3f4f6;">
      
      <!-- Main Container -->
      <div style="max-width: 650px; margin: 0 auto; background-color: #f9fafb;">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #064e3b 0%, #059669 100%); padding: 50px 30px; text-align: center; color: white;">
            <div style="font-size: 14px; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 10px; opacity: 0.8; font-weight: 600;">Morning Briefing</div>
            <h1 style="margin: 0; font-size: 34px; font-weight: 800; letter-spacing: -0.5px;">The Daily Digest</h1>
            <div style="margin-top: 20px; font-size: 15px; opacity: 0.95; background-color: rgba(255,255,255,0.2); display: inline-block; padding: 6px 18px; border-radius: 20px;">
                📅 {date_str}
            </div>
        </div>
        
        <!-- Content Body -->
        <div style="padding: 40px 25px;">
    """
    
    icons = {
        "Global News": "🌍",
        "Indian News": "🇮🇳",
        "Technology": "💻",
        "Sports": "🏆"
    }
    
    for category, url in FEEDS.items():
        icon = icons.get(category, "📰")
        html_content += f"""
          <div style="margin-bottom: 45px;">
            <h2 style="color: #111827; border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-top: 0; font-size: 22px; font-weight: 700;">
              <span style="margin-right: 12px; font-size: 24px;">{icon}</span>{category}
            </h2>
            <div style="margin-top: 25px;">
        """
        html_content += get_news(url)
        html_content += """
            </div>
          </div>
        """
        
    html_content += """
        </div>
        
        <!-- Footer -->
        <div style="background-color: #e5e7eb; padding: 35px 20px; text-align: center;">
            <p style="margin: 0; font-size: 14px; color: #4b5563; font-weight: 600;">🤖 Generated autonomously by your News Agent</p>
            <p style="margin: 10px 0 0 0; font-size: 12px; color: #6b7280;">You are receiving this because you are subscribed to the morning digest.</p>
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

if __name__ == "__main__":
    print("Fetching news from Google News RSS feeds...")
    html_email = generate_html_email()
    print("Sending email digest...")
    send_email(html_email)
    print("Agent execution complete.")
