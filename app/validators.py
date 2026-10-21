"""Server-side validation rules shared by Users, Students, Profile and Password Recovery.

The browser repeats these checks for convenience, but THESE are the ones that count.
"""
import re
from datetime import date, datetime

from app.locations import PROVINCE, match_place

STUDENT_EMAIL_DOMAIN = "holycross.edu.ph"
PERSONAL_EMAIL_DOMAIN = "gmail.com"
# The ONLY email domains the system accepts, for every kind of account.
ALLOWED_EMAIL_DOMAINS = (STUDENT_EMAIL_DOMAIN, PERSONAL_EMAIL_DOMAIN)
ALLOWED_EMAIL_MESSAGE = f"Only @{PERSONAL_EMAIL_DOMAIN} and @{STUDENT_EMAIL_DOMAIN} email addresses are accepted."
STUDENT_ID_RE = re.compile(r"[0-9]{8}")                         # exactly eight ASCII digits (fullmatch)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
NAME_EXTRA_CHARS = set(" .'-")
NAME_MAX = 60


def clean(value):
    """Trim and collapse inner whitespace: '  Ana   Liza ' -> 'Ana Liza'."""
    return " ".join((value or "").split())


def normalize_email(value):
    return (value or "").strip().lower()


def valid_person_name(value, required):
    if not value:
        return not required
    return (len(value) <= NAME_MAX and value[0].isalpha()
            and all(ch.isalpha() or ch in NAME_EXTRA_CHARS for ch in value))


def validate_names(first, middle, last):
    """Return {field: message} for the three name parts (empty dict = valid)."""
    errors = {}
    if not first:
        errors["first_name"] = "First name is required."
    elif not valid_person_name(first, True):
        errors["first_name"] = "Use letters only (spaces, . ' - allowed), up to 60 characters."
    if middle and not valid_person_name(middle, False):
        errors["middle_name"] = "Use letters only (spaces, . ' - allowed), up to 60 characters."
    if not last:
        errors["last_name"] = "Last name is required."
    elif not valid_person_name(last, True):
        errors["last_name"] = "Use letters only (spaces, . ' - allowed), up to 60 characters."
    if not errors and len(build_full_name(first, middle, last)) > 120:
        errors["last_name"] = "The full name is too long (maximum 120 characters)."
    return errors


def build_full_name(first, middle, last):
    return " ".join(part for part in (first, middle, last) if part)


def validate_email_format(email):
    """Return an error message or None. `email` must already be normalised (lower-case, trimmed).

    Besides the shape of the address, only @gmail.com and @holycross.edu.ph are accepted.
    """
    if not email:
        return "Email address is required."
    if len(email) > 120 or not EMAIL_RE.fullmatch(email):
        return "Enter a valid email address (maximum 120 characters)."
    if email.rpartition("@")[2] not in ALLOWED_EMAIL_DOMAINS:
        return ALLOWED_EMAIL_MESSAGE
    return None


def validate_student_id(student_id):
    """Exactly eight digits. No spaces, hyphens, letters, or other characters."""
    if not student_id:
        return "Student ID is required."
    if not STUDENT_ID_RE.fullmatch(student_id):
        return "Student ID must be exactly 8 digits (numbers only, no spaces or hyphens)."
    return None


def student_email_for(student_id):
    return f"{student_id}@{STUDENT_EMAIL_DOMAIN}"


def validate_student_email(email, student_id):
    """Email rule for a STUDENT account. Either:
      * a personal @gmail.com address (any name), or
      * the school address <their own 8-digit Student ID>@holycross.edu.ph.
    Every other domain is refused (see validate_email_format).
    """
    problem = validate_email_format(email)
    if problem:
        return problem
    local, _, domain = email.partition("@")
    if domain == PERSONAL_EMAIL_DOMAIN:
        return None
    if not STUDENT_ID_RE.fullmatch(local):
        return (f"A school email must be 8 digits followed by @{STUDENT_EMAIL_DOMAIN}, for example "
                f"{student_email_for('80382024')}. You can also use a personal @{PERSONAL_EMAIL_DOMAIN} address.")
    if student_id and local != student_id:
        return (f"The email's student number ({local}) does not match the Student ID ({student_id}). "
                f"It should be {student_email_for(student_id)}, or use a personal @{PERSONAL_EMAIL_DOMAIN} address.")
    return None


# ----------------------------------------------------------------- personal details
# Address (Nueva Ecija), birthday and Philippine mobile number. Used by Users, Students and Profile.

PERSONAL_FIELDS = ("barangay", "purok_street", "city_municipality", "birthdate", "contact_number")
PLACE_CHARS = set(" .,'-#/()")
MIN_AGE, MAX_AGE = 5, 120
PH_MOBILE_RE = re.compile(r"(?:09|\+639|639)([0-9]{9})")


def normalize_ph_mobile(text):
    """'+63 917-123-4567' / '639171234567' / '0917 123 4567' -> '09171234567', or None if it is not a PH mobile number."""
    compact = re.sub(r"[\s\-()]", "", text or "")
    match = PH_MOBILE_RE.fullmatch(compact)
    return "09" + match.group(1) if match else None


def _valid_place_text(value, minimum, maximum):
    return (minimum <= len(value) <= maximum and any(ch.isalnum() for ch in value)
            and all(ch.isalnum() or ch in PLACE_CHARS for ch in value))


def read_personal(form):
    """Pull the personal-detail fields out of a submitted form (Flask's request.form) and tidy them."""
    return {
        "barangay": clean(form.get("barangay")),
        "purok_street": clean(form.get("purok_street")),
        "city_municipality": clean(form.get("city_municipality")),
        "birthdate": (form.get("birthdate") or "").strip(),
        "contact_number": (form.get("contact_number") or "").strip(),
    }


def validate_personal(data):
    """Check the personal details. Returns {field: message}. On success the values in `data` are replaced by
    their clean form (official city spelling, ISO birthdate, contact number as 09XXXXXXXXX)."""
    errors = {}
    if not _valid_place_text(data["barangay"], 2, 80):
        errors["barangay"] = "Enter the barangay (2-80 characters, for example Sta. Rosa)."
    if not _valid_place_text(data["purok_street"], 2, 120):
        errors["purok_street"] = "Enter the purok, street, sitio or subdivision (2-120 characters)."
    place = match_place(data["city_municipality"])
    if place is None:
        errors["city_municipality"] = f"Choose a city or municipality of {PROVINCE}."
    else:
        data["city_municipality"] = place

    try:
        born = datetime.strptime(data["birthdate"], "%Y-%m-%d").date()
    except ValueError:
        born = None
    if born is None:
        errors["birthdate"] = "Enter a valid birthday."
    else:
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if born > today:
            errors["birthdate"] = "The birthday cannot be in the future."
        elif age < MIN_AGE or age > MAX_AGE:
            errors["birthdate"] = f"The age must be between {MIN_AGE} and {MAX_AGE} years."
        else:
            data["birthdate"] = born.isoformat()

    number = normalize_ph_mobile(data["contact_number"])
    if number is None:
        errors["contact_number"] = "Enter a Philippine mobile number, for example 09171234567 or +639171234567."
    else:
        data["contact_number"] = number
    return errors


def format_address(row):
    """'Purok 3, Brgy. Sta. Rosa, Cabanatuan City, Nueva Ecija' from a row with the address columns (or '')."""
    parts = [row.get("purok_street"), f"Brgy. {row['barangay']}" if row.get("barangay") else None,
             row.get("city_municipality"), PROVINCE if row.get("city_municipality") else None]
    return ", ".join(p for p in parts if p)
