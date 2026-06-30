import pytest
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.mark.asyncio
async def test_cors_preflight():
    """Test that an OPTIONS request returns the correct CORS headers"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/debug/cors",
            headers={
                "Origin": "https://lead-ai-khaki.vercel.app",
                "Access-Control-Request-Method": "GET",
            }
        )
        assert response.status_code == 200
        # CORSMiddleware should reflect the allowed origin
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "https://lead-ai-khaki.vercel.app"
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert "GET" in response.headers.get("access-control-allow-methods", "")

@pytest.mark.asyncio
async def test_cors_get_request():
    """Test that a standard GET request returns CORS headers"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/debug/cors",
            headers={"Origin": "https://lead-ai-khaki.vercel.app"}
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] == "https://lead-ai-khaki.vercel.app"
        assert response.headers.get("access-control-allow-credentials") == "true"

@pytest.mark.asyncio
async def test_cors_sse_endpoint():
    """Test that the SSE /events endpoint preserves CORS headers"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # We don't want to hang forever on the event stream, so we just check headers
        # Use a stream context to get the response headers immediately
        async with client.stream("GET", "/events", headers={"Origin": "https://lead-ai-khaki.vercel.app"}) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            assert "access-control-allow-origin" in response.headers
            assert response.headers["access-control-allow-origin"] == "https://lead-ai-khaki.vercel.app"
            assert response.headers.get("access-control-allow-credentials") == "true"

@pytest.mark.asyncio
async def test_cors_disallowed_origin():
    """Test that an unconfigured origin is NOT reflected (or gets rejected)"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/debug/cors",
            headers={"Origin": "https://malicious-site.com"}
        )
        assert response.status_code == 200
        # If it's not allowed, the CORS middleware omits the Access-Control-Allow-Origin header
        assert "access-control-allow-origin" not in response.headers
