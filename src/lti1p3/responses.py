"""Framework-neutral HTTP responses the library hands back to the host application."""

import html
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HttpResponse:
    """A response for the host application to send: status, headers, and a text body.

    The library never talks to a web framework directly. Map this onto your
    framework's response object (Flask, Django, FastAPI, or anything else).
    """

    statusCode: int
    headers: dict[str, str] = field(default_factory=dict[str, str])
    body: str = ""


def renderFormPost(targetUrl: str, fields: Mapping[str, str]) -> HttpResponse:
    """Render an auto-submitting HTML form, as the `response_mode=form_post` pattern in LTI 1.3 uses.

    The tool uses it to post its Deep Linking response back to the platform.
    It is not specific to Deep Linking, so any future form_post use
    (Submission Review, Platform Notification Service) can reuse it.
    """
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">\n'
        for name, value in fields.items()
    )
    page = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><title>Continue</title></head>\n"
        '<body onload="document.forms[0].submit()">\n'
        f'<form action="{html.escape(targetUrl)}" method="POST">\n'
        f'{inputs}<noscript><button type="submit">Continue</button></noscript>\n'
        "</form>\n"
        "</body>\n"
        "</html>\n"
    )
    return HttpResponse(200, {"Content-Type": "text/html; charset=UTF-8"}, page)
