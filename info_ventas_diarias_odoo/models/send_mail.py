import smtplib
from email.mime.text import MIMEText



def report_sales(body_rec):
    # Email details
    sender_email = "reportsendrevel@outlook.com"
    receiver_email = "adriii0104@hotmail.com"
    subject = "Reporte de ventas"
    body = body_rec
    password = "revelbar2023"

    # Create MIMEText object (plain text email)
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    # Sending the email using SMTP
    try:
        # Connect to the SMTP server for Outlook
        with smtplib.SMTP("smtp-mail.outlook.com", 587) as server:  # Use port 587 for TLS
            server.starttls()  # Upgrade the connection to secure using TLS
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")
