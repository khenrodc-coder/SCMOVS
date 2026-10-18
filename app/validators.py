"""Server-side validation rules shared by Users, Students, Profile and Password Recovery.

The browser repeats these checks for convenience, but THESE are the ones that count.
"""
import re

STUDENT_EMAIL_DOMAIN = "holycross.edu.ph"
# exactly eight ASCII digits (fullmatch)
STUDENT_ID_RE = re.compile(r"[0-9]{8}")
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
    """Return an error message or None. `email` must already be normalised."""
    if not email:
        return "Email address is required."
    if len(email) > 120 or not EMAIL_RE.fullmatch(email):
        return "Enter a valid email address (maximum 120 characters)."
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
    """Student email must be <8-digit Student ID>@holycross.edu.ph and match the Student ID."""
    problem = validate_email_format(email)
    if problem:
        return problem
    local, _, domain = email.partition("@")
    if domain != STUDENT_EMAIL_DOMAIN:
        return f"Student email must use the @{STUDENT_EMAIL_DOMAIN} domain."
    if not STUDENT_ID_RE.fullmatch(local):
        return f"Student email must be 8 digits followed by @{STUDENT_EMAIL_DOMAIN}, for example {student_email_for('80382024')}."
    if student_id and local != student_id:
        return (f"The email's student number ({local}) does not match the Student ID ({student_id}). "
                f"It should be {student_email_for(student_id)}.")
    return None
