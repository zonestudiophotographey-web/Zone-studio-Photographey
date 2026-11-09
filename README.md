# ZONE STUDIO app

The project is separated for independent hosting:

- `frontend/` is the static HTML, CSS, JavaScript, and assets. Deploy this folder with GitHub Pages.
- `backend/` is the Python Flask API. The root `render.yaml` configures Render to use this folder as a web service.

## Connect the deployments

1. In Render, create a Blueprint from this repository using the root `render.yaml`. It sets `backend/` as the service root and starts Gunicorn.
2. Add the backend environment variables from `backend/.env.example` in Render: Neon `DATABASE_URL`, the GitHub Pages origin in `FRONTEND_ORIGIN`, Cloudinary credentials, and a long random `STUDIO_UPLOAD_KEY`.
3. Set `window.ZONE_API_BASE` in `frontend/api-config.js` to the Render service URL, such as `https://zone-studio-api.onrender.com` (no trailing slash).
4. Enable GitHub Pages with GitHub Actions as the source. The workflow at `.github/workflows/pages.yml` publishes `frontend/` after each push to `main`. Booking submissions and registration/login requests will then go to Flask.

The Flask API creates its Neon tables at startup. It provides `/api/health`, `/api/bookings`, `/api/auth/register`, `/api/auth/login`, and the protected Cloudinary image endpoint `/api/images`. Keep Neon and Cloudinary secrets in Render environment settings; only the public Render URL belongs in the frontend.

For local development, install `backend/requirements.txt`, set the environment variables, then run `flask --app app run` from `backend/`. Serve `frontend/` over HTTP and set its `api-config.js` URL to `http://localhost:5000`.

Admin authorization, booking retrieval for customer accounts, email notifications, and payment processing are not included. The existing demo admin PIN is frontend-only and is not production security.

