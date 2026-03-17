from __future__ import annotations

import base64
import io

import qrcode


def make_qr_data_uri(text: str) -> str:
    image = qrcode.make(text)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
