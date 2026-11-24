"""Session cookie settings shared by the authentication endpoints.

Sessions live in Redis with a per-key TTL (see ``session_store``), so no
periodic cleanup job is needed; the login and SSO endpoints set the cookie
themselves.
"""

import os

SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)
SESSION_SAMESITE = os.getenv("SESSION_SAMESITE", "Lax")  # Lax or Strict
