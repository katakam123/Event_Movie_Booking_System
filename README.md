# Event & Movie Ticket Booking System

A backend application built with **FastAPI** for booking event and movie tickets. The system supports user authentication, event and show management, seat selection, temporary seat locking, booking, online payments, QR-code ticket generation, ticket validation, cancellations, waitlists, reports, and real-time seat updates.

---

## 1. Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.12 | Backend programming |
| FastAPI | REST API development |
| Pydantic | Request validation and response schemas |
| SQLAlchemy | ORM and database operations |
| MySQL | Relational database |
| Alembic | Database migrations |
| Redis | Temporary seat locks and caching |
| JWT | Authentication |
| Passlib / bcrypt | Password hashing |
| Razorpay | Online payment integration |
| WebSockets | Real-time seat map updates |
| APScheduler | Scheduled background jobs |
| FastAPI BackgroundTasks | Background processing |
| SMTP | Email notifications |
| QRCode | Ticket QR-code generation |
| ReportLab | PDF ticket generation |
| Pytest | Automated testing |

---

## 2. Project Features

- User registration and login.
- Role-based access control.
- Admin and organizer management.
- Event, venue and show management.
- Seat map and seat category management.
- Temporary seat locking using Redis.
- Booking creation and booking expiry.
- Online payment using Razorpay.
- Payment verification and webhook handling.
- PDF ticket generation with QR codes.
- QR-code ticket scanning and validation.
- Ticket cancellation and refund management.
- Waitlist management.
- Real-time seat map updates through WebSockets.
- Sales and booking reports.
- Email notifications.
- Scheduled background tasks.

---

## 3. Project Structure

The project is organized into modules similar to the following:

```text
Event_movie_booking/
│
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   │
│   ├── models/
│   ├── schemas/
│   ├── routers/
│   ├── services/
│   ├── utils/
│   ├── websockets/
│   └── jobs/
│
├── alembic/
│   ├── versions/
│   └── env.py
│
├── tests/
│
├── .env
├── .env.example
├── .gitignore
├── alembic.ini
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

The actual project may contain additional files and modules.

---

## 4. Prerequisites

Install the following software:

1. Python 3.12
2. Visual Studio Code
3. MySQL Server
4. Redis
5. Git
6. Docker Desktop (for Docker deployment)

Check Python:

```powershell
python --version
```

Check pip:

```powershell
python -m pip --version
```

---

## 5. Clone the Project

```powershell
git clone YOUR_GITHUB_REPOSITORY_URL
```

Move into the project folder:

```powershell
cd Event_movie_booking
```

Open the project in VS Code:

```powershell
code .
```

---

## 6. Create and Activate Virtual Environment

Create the virtual environment:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate again:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

---

## 7. MySQL Database Setup

Start the MySQL server.

Open MySQL Workbench or the MySQL command line and create the database:

```sql
CREATE DATABASE event_movie_booking;
```

Configure the database connection in `.env`.

Example:

```env
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/event_movie_booking
```

Replace `YOUR_PASSWORD` with your actual MySQL password.

If the password contains special characters such as `@`, `#`, or `/`, URL-encode those characters in the connection string.

Do not commit your real database password to GitHub.

---

## 8. Redis Setup

Redis is used for temporary seat locks and related short-lived data.

### Option A: Run Redis using Docker

Start Redis:

```powershell
docker run -d --name event-redis -p 6379:6379 redis:7-alpine
```

Check the container:

```powershell
docker ps
```

Check Redis connectivity:

```powershell
docker exec -it event-redis redis-cli ping
```

Expected response:

```text
PONG
```

Redis URL:

```env
REDIS_URL=redis://localhost:6379/0
```

To stop Redis:

```powershell
docker stop event-redis
```

To start it again:

```powershell
docker start event-redis
```

### Option B: Use an existing Redis installation

Start your Redis server and configure the correct connection URL in `.env`.

---

## 9. Environment Variables

Create a `.env` file in the project root.

Example configuration:

```env
# Application
APP_NAME=Event Movie Booking System
DEBUG=True

# MySQL
DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@localhost:3306/event_movie_booking

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
SECRET_KEY=CHANGE_TO_A_LONG_RANDOM_SECRET
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Seat locking
SEAT_LOCK_SECONDS=300
BOOKING_EXPIRY_MINUTES=10

# Ticket security
TICKET_HMAC_SECRET=CHANGE_TO_A_RANDOM_SECRET

# Razorpay Test Mode
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY_ID
RAZORPAY_KEY_SECRET=YOUR_RAZORPAY_SECRET
RAZORPAY_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET

# SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=YOUR_EMAIL@gmail.com
SMTP_PASSWORD=YOUR_GMAIL_APP_PASSWORD
SMTP_FROM_EMAIL=YOUR_EMAIL@gmail.com
SMTP_FROM_NAME=Event Movie Booking System
SMTP_USE_TLS=True
```

**Important:**

- Use Razorpay test-mode credentials during development.
- Generate strong secret values for JWT and ticket security.
- Never upload `.env` to GitHub.
- Keep `.env.example` free of actual passwords and secret keys.
- Environment variable names must match the settings defined in `app/config.py`.

---

## 10. Alembic Database Migrations

Alembic manages database schema changes.

### Check the current migration

```powershell
alembic current
```

### Check migration history

```powershell
alembic history
```

### Create a migration

After updating SQLAlchemy models:

```powershell
alembic revision --autogenerate -m "describe your database changes"
```

Review the generated migration file before applying it.

### Apply migrations

```powershell
alembic upgrade head
```

### Roll back one migration

```powershell
alembic downgrade -1
```

### Check the current migration head

```powershell
alembic heads
```

**Important:** Do not use `Base.metadata.create_all()` as a replacement for Alembic migrations. Keep the migration files in the repository so another developer can recreate the database schema.

---

## 11. SMTP Email Configuration

SMTP is used to send application email notifications.

For Gmail:

1. Enable 2-Step Verification on your Google account.
2. Generate a Google App Password.
3. Put the generated App Password in `SMTP_PASSWORD`.
4. Configure the SMTP host and port.

Example:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=YOUR_EMAIL@gmail.com
SMTP_PASSWORD=YOUR_GMAIL_APP_PASSWORD
SMTP_FROM_EMAIL=YOUR_EMAIL@gmail.com
SMTP_USE_TLS=True
```

Do not use your normal Gmail account password.

Email functionality should be tested with a dedicated development email account before deployment.

---

## 12. Razorpay Payment Setup

The project uses Razorpay for online payments.

### Configure test credentials

1. Create or access a Razorpay account.
2. Open the Razorpay Dashboard.
3. Switch to Test Mode.
4. Generate the test API Key ID and Key Secret.
5. Configure the credentials in `.env`.

```env
RAZORPAY_KEY_ID=rzp_test_YOUR_KEY_ID
RAZORPAY_KEY_SECRET=YOUR_RAZORPAY_SECRET
RAZORPAY_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET
```

### Payment workflow

1. Customer creates a booking.
2. Backend validates the booking and seat locks.
3. Backend creates a Razorpay order.
4. Frontend completes the payment using Razorpay Checkout.
5. Frontend sends payment verification details to the backend.
6. Backend verifies the Razorpay payment signature.
7. Backend confirms the booking only after successful verification.
8. Backend generates the ticket and QR code.
9. Razorpay webhooks provide additional payment status notifications.

Known API routes discussed during implementation:

```text
POST /bookings/{booking_id}/pay
POST /bookings/{booking_id}/verify-payment
POST /webhooks/razorpay
```

The exact request and response schemas should be checked in Swagger.

### Webhook configuration

Configure the webhook URL in the Razorpay Dashboard:

```text
https://YOUR_PUBLIC_DOMAIN/webhooks/razorpay
```

For local development, expose the application using a secure tunneling service and configure the resulting public URL.

Subscribe to the payment events handled by the application, including:

```text
payment.captured
payment.failed
```

The webhook secret in Razorpay must match `RAZORPAY_WEBHOOK_SECRET`.

---

## 13. Run the Application

Ensure MySQL and Redis are running.

Activate the virtual environment:

```powershell
.venv\Scripts\Activate.ps1
```

Start FastAPI:

```powershell
uvicorn app.main:app --reload
```

Expected local URL:

```text
http://127.0.0.1:8000
```

Open Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

Open ReDoc:

```text
http://127.0.0.1:8000/redoc
```

Use Swagger to register users, authenticate, create events, manage shows, select seats, create bookings and test the available API endpoints.

---

## 14. User Roles and Test Credentials

The application uses role-based access control.

| Role | Responsibilities |
|---|---|
| Admin | Manage users, organizers and system operations |
| Organizer | Manage permitted events, venues and shows |
| Customer | Browse shows, book seats, pay and manage tickets |

### Test account setup

Create test accounts in your local development database using the application's registration and admin-user creation workflows.

| Role | Email | Password |
|---|---|---|
| Admin | Create using admin setup workflow | Set during admin creation |
| Organizer | Create using registration/admin workflow | Set during account creation |
| Customer | Create using public registration | Set during registration |

**Note:** Actual test email addresses and passwords have not yet been supplied. Add your verified local test credentials here after creating the accounts. Never publish production credentials or real user passwords in this README.

### Authentication testing

1. Open Swagger.
2. Find the login endpoint.
3. Enter the test account credentials.
4. Copy the returned access token if needed.
5. Click **Authorize** in Swagger.
6. Enter the token using the authentication format expected by the API.
7. Test endpoints allowed for that role.
8. Verify that unauthorized roles receive the appropriate error response.

---

## 15. WebSocket Testing

WebSockets provide real-time seat map updates.

### Testing procedure

1. Start the FastAPI server.
2. Open the frontend or WebSocket test client in two browser tabs.
3. Connect both clients to the same show or seat-map WebSocket endpoint.
4. Select and lock a seat in the first tab.
5. Observe the seat status in the second tab.
6. Release the seat or allow the lock to expire.
7. Confirm that the updated status is received by connected clients.

### Expected behavior

- Both clients should receive relevant seat map updates.
- A seat locked by one customer should not be available to another customer during the lock period.
- Expired locks should no longer prevent another customer from selecting the seat.
- WebSocket clients should receive the events defined by the application's implementation.

**Note:** Insert the exact WebSocket URL, event names, and authentication requirements from the implemented WebSocket router here. They have not yet been confirmed.

---

## 16. Ticket PDF and QR Code Testing

After a successful booking and payment:

1. Open the booking or ticket endpoint in Swagger.
2. Retrieve the generated ticket.
3. Download the PDF.
4. Open the PDF and verify the ticket information.
5. Scan the QR code using a QR scanner or the application's ticket validation endpoint.
6. Verify that the first valid scan is accepted.
7. Scan the same ticket again.
8. Verify that a repeated scan is rejected according to the ticket validation rules.

The ticket should contain the information generated by the application, such as booking reference, show details and ticket identification.

---

## 17. Automated Testing

Install testing dependencies if they are not already present:

```powershell
python -m pip install pytest pytest-asyncio httpx
```

Run all tests:

```powershell
pytest -v
```

Run a particular test file:

```powershell
pytest tests/test_seat_locking.py -v
```

Recommended test coverage:

- Redis seat-lock ownership and expiration.
- Prevention of conflicting seat bookings.
- Single empty seat rule.
- Successful payment verification.
- Failed payment handling.
- Invalid payment signature rejection.
- Repeated payment webhook handling.
- Booking cancellation time restrictions.
- Ticket validation and repeated scan rejection.

Use a separate test database and test Redis instance. Do not run destructive tests against production data.

---

## 18. Sales Report Export

The application includes sales reporting functionality.

The Excel report should be tested by:

1. Creating bookings and completing test payments.
2. Opening the sales report endpoint.
3. Requesting the report for the desired date range.
4. Downloading the generated Excel file.
5. Opening it in Microsoft Excel or LibreOffice.
6. Checking the booking, ticket and sales totals against the database.

The exact report endpoint and spreadsheet columns should match the implementation.

---

## 19. Docker Deployment

The project includes Docker support for:

- FastAPI application.
- MySQL database.
- Redis service.

Build and start the services:

```powershell
docker compose up --build
```

Run in detached mode:

```powershell
docker compose up -d --build
```

Check running containers:

```powershell
docker compose ps
```

View application logs:

```powershell
docker compose logs -f app
```

Stop the services:

```powershell
docker compose down
```

Stop services and remove named volumes:

```powershell
docker compose down -v
```

**Warning:** The `-v` option removes the Compose-managed database volumes and may delete your database data. Use it only when that is intended.

The Docker environment should use service names for internal connections, such as the MySQL and Redis service names, rather than `localhost`.

---

## 20. Screenshots and Demonstration Checklist

Capture screenshots from the actual running application.

### Swagger API screenshots

- [ ] Swagger documentation page.
- [ ] Successful user registration.
- [ ] Successful login.
- [ ] Admin-protected API.
- [ ] Organizer-protected API.
- [ ] Customer booking API.
- [ ] Seat locking API.
- [ ] Booking confirmation.

### Payment and ticket screenshots

- [ ] Successful Razorpay test payment.
- [ ] Failed Razorpay test payment.
- [ ] Generated PDF ticket with QR code.
- [ ] Successful QR ticket scan.
- [ ] Repeated QR scan rejected.

### Real-time seat map demonstration

- [ ] Two browser tabs connected to the same show.
- [ ] Seat selection in the first tab.
- [ ] Updated seat status visible in the second tab.
- [ ] Seat release or lock expiration update.

### Project files

- [ ] README.md.
- [ ] All Alembic migration files.
- [ ] requirements.txt.
- [ ] .env.example.
- [ ] Dockerfile.
- [ ] docker-compose.yml.
- [ ] Automated test files.

---

## 21. Business Rules and Assumptions

The following rules describe the intended system behavior. Confirm the exact implementation before treating each rule as complete.

1. Only authenticated users can access protected booking operations.
2. Admin, Organizer and Customer roles have different permissions.
3. Seat locking uses Redis and is temporary.
4. A customer cannot book a seat already reserved or booked by another customer.
5. A booking remains pending until payment is successfully verified.
6. Invalid payment signatures must not confirm bookings.
7. Razorpay webhooks are used to process payment status events.
8. Ticket QR codes are generated for confirmed bookings.
9. A ticket must not be accepted repeatedly if it has already been used.
10. Booking cancellation must follow the configured cancellation policy.
11. Expired bookings and seat locks must be handled by the application's expiry logic.
12. WebSocket events keep connected seat maps synchronized.
13. Database schema changes must be managed using Alembic.
14. Payment testing should use Razorpay Test Mode.
15. Secrets and credentials must be stored in environment variables, not committed to source control.

### Pricing and coupon assumptions for planned features

- Dynamic pricing: increase ticket prices by 10% when a show is more than 80% booked.
- Best seat suggestion: recommend available adjacent seats for the requested seat count and category.
- Coupons: validate minimum ticket count and coupon expiry before applying a discount.

These planned features should be marked complete only after implementation and testing.

---

## 22. Git Commands

Check modified files:

```powershell
git status
```

Stage project files:

```powershell
git add .
```

Commit changes:

```powershell
git commit -m "Add Event and Movie Ticket Booking System documentation"
```

Push to GitHub:

```powershell
git push origin main
```

Do not commit `.env`, virtual environments, database files or other private credentials.

---

## 23. Troubleshooting

### MySQL connection error

- Verify MySQL is running.
- Check the database name and password.
- Verify the port is correct.
- Check URL encoding for special password characters.

### Redis connection error

- Verify Redis is running.
- Test Redis using `redis-cli ping`.
- Check `REDIS_URL`.

### Alembic migration error

- Run `alembic current`.
- Run `alembic history`.
- Check migration dependencies and `down_revision`.
- Review generated migration files before applying them.

### Module not found

Activate the virtual environment and install dependencies:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Application startup error

Run:

```powershell
python -m py_compile app/main.py
```

Then inspect the complete traceback in the terminal.

---

## 24. Security Notes

- Never commit `.env` or private API credentials.
- Use strong JWT and ticket signing secrets.
- Use HTTPS in production.
- Verify Razorpay payment signatures on the backend.
- Verify webhook signatures using the raw request body.
- Protect admin and organizer endpoints with role checks.
- Use a separate test database for automated tests.
- Do not use Razorpay test credentials in production.

---

## 25. Project Status

**Project:** Event & Movie Ticket Booking System  
**Backend Framework:** FastAPI  
**Database:** MySQL  
**Cache and Seat Locking:** Redis  
**Payment Gateway:** Razorpay  
**API Documentation:** Swagger / OpenAPI

The implementation, automated tests, screenshots, and deployment configuration should be verified before marking the project as fully completed.

