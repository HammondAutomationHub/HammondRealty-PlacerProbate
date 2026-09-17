"""Constants for Placer Probate Monitor."""

DOMAIN = "placer_probate_monitor"

CONF_RECIPIENTS = "recipients"
CONF_SMTP_HOST = "smtp_host"
CONF_SMTP_PORT = "smtp_port"
CONF_SMTP_USER = "smtp_user"
CONF_SMTP_PASSWORD = "smtp_password"
CONF_MAIL_FROM = "mail_from"
CONF_SEND_EMAIL = "send_email"
CONF_FREQUENCY = "frequency"
CONF_RUN_TIME = "run_time"
CONF_WEEKLY_DAY = "weekly_day"
CONF_MONTHLY_DAY = "monthly_day"
CONF_TIMEZONE = "timezone"
CONF_RUN_ON_START = "run_on_start"
CONF_LOOKBACK_DAYS = "lookback_days"
CONF_LOOKAHEAD_DAYS = "lookahead_days"
CONF_COUNTY = "county"
CONF_KEYWORDS = "keywords"
CONF_SKIP_PORTAL = "skip_portal"
CONF_GENERATE_PDF = "generate_pdf"
CONF_ECOURT_PAUSE = "ecourt_pause_seconds"
CONF_MAX_PAGES = "max_search_pages"

FREQUENCIES = ["hourly", "daily", "weekdays", "weekly", "monthly"]
WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DEFAULTS = {
    CONF_RECIPIENTS: "",
    CONF_SMTP_HOST: "smtp.gmail.com",
    CONF_SMTP_PORT: 587,
    CONF_SMTP_USER: "",
    CONF_SMTP_PASSWORD: "",
    CONF_MAIL_FROM: "",
    CONF_SEND_EMAIL: True,
    CONF_FREQUENCY: "daily",
    CONF_RUN_TIME: "08:30:00",
    CONF_WEEKLY_DAY: "monday",
    CONF_MONTHLY_DAY: 1,
    CONF_TIMEZONE: "America/Los_Angeles",
    CONF_RUN_ON_START: False,
    CONF_LOOKBACK_DAYS: 21,
    CONF_LOOKAHEAD_DAYS: 21,
    CONF_COUNTY: "Placer",
    CONF_KEYWORDS: '"NOTICE OF PETITION TO ADMINISTER ESTATE"',
    CONF_SKIP_PORTAL: False,
    CONF_GENERATE_PDF: True,
    CONF_ECOURT_PAUSE: 1.2,
    CONF_MAX_PAGES: 10,
}

ATTR_LAST_RUN = "last_run"
ATTR_LAST_RESULT = "last_result"
ATTR_LAST_ERROR = "last_error"
ATTR_NEW_COUNT = "new_count"
ATTR_PDF = "pdf"
