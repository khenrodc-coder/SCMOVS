"""Text of outgoing emails."""
from html import escape


def reset_email(link, minutes):
    subject = "SCMOVS — Password Reset Request"
    text = (
        "Hello,\n\n"
        "We received a request to reset the password for your Student Council Management and "
        "Online Voting System account.\n\n"
        "To create a new password, use the secure link below:\n\n"
        f"{link}\n\n"
        f"This link expires in {minutes} minutes and can only be used once.\n\n"
        "If you did not request this reset, you may safely ignore this email.\n\n"
        "SCMOVS Support\n")
    safe = escape(link, quote=True)
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;color:#1e293b">'
        '<p>Hello,</p>'
        '<p>We received a request to reset the password for your Student Council Management and '
        'Online Voting System account.</p>'
        '<p>To create a new password, use the secure link below:</p>'
        f'<p style="margin:24px 0"><a href="{safe}" style="background:#1e3a8a;color:#fff;padding:12px 22px;'
        'border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block">Reset My Password</a></p>'
        f'<p style="font-size:13px;color:#475569">If the button does not work, copy this address into your browser:<br>'
        f'<span style="word-break:break-all">{safe}</span></p>'
        f'<p>This link expires in {minutes} minutes and can only be used once.</p>'
        '<p>If you did not request this reset, you may safely ignore this email.</p>'
        '<p>SCMOVS Support</p></div>')
    return subject, text, html


def welcome_email(full_name, username, password, login_url, system_name):
    """Email sent to a NEW account holder with their initial password."""
    subject = "SCMOVS \u2014 Your Account Has Been Created"
    text = (
        f"Hello {full_name},\n\n"
        f"An account was created for you in the {system_name}.\n\n"
        f"Username: {username}\n"
        f"Initial password: {password}\n\n"
        f"Sign in here: {login_url}\n\n"
        "You will be asked to choose a new password the first time you sign in. "
        "Please do not share this password with anyone.\n\n"
        "If you were not expecting this email, please contact the school administration.\n\n"
        "SCMOVS Support\n")
    e = lambda value: escape(str(value), quote=True)
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;color:#1e293b">'
        f'<p>Hello {e(full_name)},</p>'
        f'<p>An account was created for you in the {e(system_name)}.</p>'
        '<table style="border-collapse:collapse;margin:16px 0;font-size:15px">'
        f'<tr><td style="padding:6px 14px 6px 0;color:#475569">Username</td><td style="font-weight:bold">{e(username)}</td></tr>'
        f'<tr><td style="padding:6px 14px 6px 0;color:#475569">Initial password</td>'
        f'<td style="font-family:Consolas,Menlo,monospace;font-weight:bold;letter-spacing:1px">{e(password)}</td></tr></table>'
        f'<p style="margin:24px 0"><a href="{e(login_url)}" style="background:#1e3a8a;color:#fff;padding:12px 22px;'
        'border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block">Sign in</a></p>'
        '<p>You will be asked to choose a new password the first time you sign in. Please do not share this password with anyone.</p>'
        '<p style="font-size:13px;color:#475569">If you were not expecting this email, please contact the school administration.</p>'
        '<p>SCMOVS Support</p></div>')
    return subject, text, html
