from __future__ import annotations

import sys
from pathlib import Path

import environ
import sentry_sdk
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

# Security

SECRET_KEY = env("SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Sentry (production only)
if not DEBUG:
    sentry_sdk.init(
        dsn=env("SENTRY_DSN", default=""),
        environment="production",
        send_default_pii=True,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        before_send=lambda event, hint: event
        if event.get("logger") != "django.security.DisallowedHost"
        else None,
    )

# Application definition

INSTALLED_APPS = [
    "channels",
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "bot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "synthhive.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "synthhive.asgi.application"
WSGI_APPLICATION = "synthhive.wsgi.application"

# Database

DATABASES = {
    "default": env.db(
        default="postgresql://synthhive:synthhive@localhost:5432/synthhive"
    )
}
# Connection pooling in production only. Under pytest the pool's background
# worker thread holds connections across the test transaction and can wedge
# event-loop/process teardown, so leave it off for tests (and for SQLite,
# which rejects the option).
_UNDER_TEST = "pytest" in sys.modules


def production_database_extras(engine: str, *, under_test: bool) -> dict:
    """The DB config that ships to production — pure, so tests can see it.

    Because the pool is off under pytest, the production branch below is
    invisible to an ordinary test run: a fully green suite crash-looped prod
    on 2026-08-22 (a `check` key colliding with the one Django passes
    itself). tests/test_production_db_config.py asserts on this function's
    output with under_test=False.

    CONN_HEALTH_CHECKS is the pool's `check` callback (Django forwards it).
    Left False, a Postgres restart leaves the pool serving dead connections
    forever — 2026-08-21: every bot raised "the connection is closed" for
    ~3h while the container read Up and the panel returned 200. Never put
    `check` in the pool options yourself.
    """
    if engine == "django.db.backends.sqlite3" or under_test:
        return {}
    return {
        "CONN_HEALTH_CHECKS": True,
        # Explicit sizing: the bare `pool: True` default caps at 4
        # connections, which a handful of concurrent requests can exhaust.
        # timeout keeps a starved pool failing fast instead of hanging
        # every request for 30s (the 2026-07-31 "constant Loading" outage).
        "OPTIONS": {"pool": {"min_size": 2, "max_size": 20, "timeout": 10}},
    }


DATABASES["default"].update(
    production_database_extras(DATABASES["default"]["ENGINE"], under_test=_UNDER_TEST)
)

# Auth

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# Twitch

TWITCH_CLIENT_ID = env("TWITCH_CLIENT_ID", default="")
TWITCH_CLIENT_SECRET = env("TWITCH_CLIENT_SECRET", default="")

# Synthfunc

SYNTHFUNC_API_URL = env("SYNTHFUNC_API_URL", default="http://localhost:7178/api")
SYNTHFUNC_API_KEY = env("SYNTHFUNC_API_KEY", default="")

# Content Security Policy (Django 6.0+)

SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF, "wss:", "ws:"],
    "frame-src": [CSP.NONE],
}
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"

# Encryption

FERNET_KEY = env("FERNET_KEY", default="")
SALT_KEY = FERNET_KEY

# Logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "bot": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
