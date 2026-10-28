"""Tests for the auto-submitting form_post page used to hand a JWT back to the platform."""

from lti1p3.responses import renderFormPost


class TestRenderFormPost:
    def test_rendersAnHtmlFormPostingToTheTargetUrl(self):
        targetUrl = "https://platform.example.com/deep-link-return"
        response = renderFormPost(targetUrl, {"JWT": "the-jwt-value"})
        assert response.statusCode == 200
        assert "text/html" in response.headers["Content-Type"]
        assert f'action="{targetUrl}"' in response.body
        assert 'method="POST"' in response.body

    def test_usesTheExactFieldNamesAndValuesGiven(self):
        html = renderFormPost("https://example.com", {"JWT": "abc.def.ghi"}).body
        assert 'name="JWT"' in html
        assert 'value="abc.def.ghi"' in html
        assert 'name="id_token"' not in html

    def test_autoSubmitsViaJavascriptWithANoscriptFallback(self):
        html = renderFormPost("https://example.com", {"JWT": "x"}).body
        assert ".submit()" in html
        assert "<noscript>" in html

    def test_escapesHtmlSpecialCharactersInFieldValues(self):
        html = renderFormPost("https://example.com", {"field": '"><script>alert(1)</script>'}).body
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapesTheTargetUrl(self):
        html = renderFormPost('https://example.com/"><script>x</script>', {"JWT": "x"}).body
        assert "<script>x</script>" not in html

    def test_rendersMultipleFields(self):
        html = renderFormPost("https://example.com", {"a": "1", "b": "2"}).body
        for fragment in ('name="a"', 'value="1"', 'name="b"', 'value="2"'):
            assert fragment in html
