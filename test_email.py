from app.utils.email import send_email

result = send_email(
    recipient="saikatakam07@gmail.com",
    subject="Event Booking System Test",
    body="Your SMTP email configuration is working successfully.",
)

print("Email sent:", result)