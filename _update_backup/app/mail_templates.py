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
