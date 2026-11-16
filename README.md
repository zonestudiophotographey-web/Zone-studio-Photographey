# ZONE STUDIO

The website uses a static frontend and a Flask API backed by PostgreSQL. The frontend's `api-config.js` contains the public API URL.

## Administrator access

Customer accounts are created through the website. Public registration cannot create administrator accounts.

To bootstrap the first administrator, set `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` (at least 14 characters), and `INITIAL_ADMIN_NAME` on the backend service, then restart or deploy it. The API inserts this account only if the email is not already registered; it does not reset the password on later restarts. Choose an email that is not already used by a customer account. After creation, remove the three bootstrap variables from the hosting environment. Keep the password in the host's secret settings, not in this repository.

## Backend settings

Set `DATABASE_URL`, `FRONTEND_ORIGIN`, and the Cloudinary credentials (`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`). Cloudinary is required for admin photo uploads. See `backend/.env.example` for the variable names.

The administrator workspace manages customers, bookings and statuses, services, categorized photo uploads, and contact messages. Customer accounts can update profile details and see their own booking activity. This site does not process payments.

For local development, install `backend/requirements.txt`, configure the environment values, run `flask --app app run` from `backend/`, and serve `frontend/` over HTTP.
