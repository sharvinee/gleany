"""Composio send_advisory — sends email via Gmail through Composio.

Called from OUTSIDE the agent loop, only after human confirmation.
The agent never holds this as a tool — it's a structural gate.

If no Gmail account is connected to Composio, falls back to terminal print.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv


def send_advisory_via_composio(
    recipient_email: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
) -> str:
    """Send an advisory email via Composio's Gmail integration.

    This function is called from outside the agent loop after explicit
    human confirmation. If Composio is not configured or no Gmail account
    is connected, it falls back to printing to the terminal.

    Args:
        recipient_email: The recipient's email address.
        subject:         Email subject line.
        body:            Email body (plain text).
        cc:              Optional CC recipients.

    Returns:
        Confirmation string.
    """
    load_dotenv()
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        return _terminal_fallback(recipient_email, subject, body)

    try:
        from composio import Composio

        c = Composio(api_key=api_key)

        # Check for a connected Gmail account
        accounts = c.connected_accounts.list(toolkit_slugs=["Gmail"])
        if not accounts.items:
            print("⚠️  No Gmail account connected to Composio.")
            print("   Connect one at https://app.composio.dev → Connected Accounts → Gmail")
            return _terminal_fallback(recipient_email, subject, body)

        # Find the active connection
        connected_account = None
        for acc in accounts.items:
            if hasattr(acc, "status") and acc.status == "ACTIVE":
                connected_account = acc
                break

        if not connected_account:
            print("⚠️  Gmail account connected but not ACTIVE.")
            return _terminal_fallback(recipient_email, subject, body)

        # Execute GMAIL_SEND_EMAIL
        # dangerously_skip_version_check avoids needing to pin a toolkit version
        # for this demo. In production you'd pin the version.
        result = c.tools.execute(
            slug="GMAIL_SEND_EMAIL",
            arguments={
                "recipient_email": recipient_email,
                "subject": subject,
                "body": body,
                "cc": cc or [],
                "user_id": "me",
            },
            connected_account_id=connected_account.id,
            user_id="default",
            dangerously_skip_version_check=True,
        )

        return f"✅ Advisory email sent to {recipient_email} via Composio Gmail."

    except Exception as e:
        print(f"⚠️  Composio send failed: {e}")
        return _terminal_fallback(recipient_email, subject, body)


def _terminal_fallback(recipient: str, subject: str, body: str) -> str:
    """Print the advisory to terminal as a fallback."""
    print(f"\n{'='*60}")
    print("ADVISORY (terminal fallback — Composio Gmail not connected)")
    print(f"  To:      {recipient}")
    print(f"  Subject: {subject}")
    print(f"  Body:")
    # Print first 500 chars of body indented
    for line in body[:500].splitlines():
        print(f"    {line}")
    if len(body) > 500:
        print(f"    ... ({len(body) - 500} more chars)")
    print(f"{'='*60}")
    return f"Advisory printed to terminal (fallback). Recipient: {recipient}"
