def test_qr_lines_are_non_empty():
    from console.ui import qr_lines
    lines = qr_lines("https://example.com")
    assert len(lines) > 5
    assert all(isinstance(l, str) for l in lines)


def test_status_line_contains_key_fields():
    from console.ui import format_status
    line = format_status(
        connected=True,
        listener_count=2,
        elapsed_s=90,
        last_phrase="Hello world",
    )
    assert "LIVE" in line
    assert "2" in line
    assert "1:30" in line
    assert "Hello world" in line
