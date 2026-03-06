import io
import qrcode


def qr_lines(url: str) -> list:
    """Return the QR code for `url` as a list of ASCII art strings."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf)
    return buf.getvalue().splitlines()


def format_status(
    connected: bool,
    listener_count: int,
    elapsed_s: int,
    last_phrase: str,
) -> str:
    state = "LIVE" if connected else "OFFLINE"
    mins, secs = divmod(elapsed_s, 60)
    phrase = (last_phrase[:60] + "…") if len(last_phrase) > 60 else last_phrase
    return f"[{state}] listeners={listener_count}  elapsed={mins}:{secs:02d}  last=\"{phrase}\""
