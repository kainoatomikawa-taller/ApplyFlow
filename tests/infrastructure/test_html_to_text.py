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


# ---- Escaped HTML ------------------------------------------------------------
#
# Greenhouse sends `content` with its tags escaped. Stripping tags and *then*
# unescaping turned `&lt;p&gt;` back into `<p>`, so every Greenhouse description
# was stored as markup. Found by reading a real board.


def test_escaped_html_is_reduced_to_text_not_turned_back_into_markup():
    escaped = "&lt;h2&gt;Who we are&lt;/h2&gt;&lt;p&gt;We build things.&lt;/p&gt;"

    result = html_to_text(escaped)

    assert "<" not in result
    assert result == "Who we are\nWe build things."


def test_escaped_script_content_is_dropped_on_the_second_pass():
    escaped = "&lt;p&gt;Keep this&lt;/p&gt;&lt;script&gt;evil()&lt;/script&gt;"

    assert html_to_text(escaped) == "Keep this"


def test_an_angle_bracket_in_prose_is_not_mistaken_for_a_tag():
    """The second pass is gated on something tag-shaped. "&lt;5ms" is a latency
    figure, and stripping it would delete a requirement rather than clean it."""
    assert html_to_text("<p>Serves requests in &lt;5ms</p>") == (
        "Serves requests in <5ms"
    )


def test_entities_that_are_not_markup_still_resolve():
    assert html_to_text("<p>Ben &amp; Jerry&#39;s</p>") == "Ben & Jerry's"


def test_a_description_quoting_a_tag_keeps_it_after_two_passes():
    """Double-escaped markup is a posting showing the reader a tag on purpose.
    Two passes is the cap precisely so this survives."""
    assert html_to_text("&lt;p&gt;Use &amp;lt;div&amp;gt; here&lt;/p&gt;") == (
        "Use <div> here"
    )
