from src.infrastructure.ats_boards.html_to_text import html_to_text


def test_strips_tags_and_collapses_block_boundaries_into_newlines():
    html = "<p>Build <b>great</b> things.</p><p>Join our team.</p>"
    assert html_to_text(html) == "Build great things.\nJoin our team."


def test_unescapes_html_entities():
    assert html_to_text("<p>Salt &amp; pepper</p>") == "Salt & pepper"


def test_strips_script_and_style_content_entirely():
    html = "<style>.a{color:red}</style><p>Real content.</p><script>evil()</script>"
    assert html_to_text(html) == "Real content."


def test_empty_input_yields_empty_string():
    assert html_to_text("") == ""
