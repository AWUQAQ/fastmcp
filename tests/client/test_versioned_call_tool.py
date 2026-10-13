"""Version-pinned call_tool must not validate against the highest version's
output schema.

The session's output-schema cache is keyed by tool name and holds only the
highest version's schema (list_tools deduplicates), so a pinned call's result
was validated and hydrated against a schema that does not describe it.

Related issue: https://github.com/PrefectHQ/fastmcp/issues/5721
"""

import asyncio

import pytest

from fastmcp import Client, FastMCP


@pytest.fixture
def server() -> FastMCP:
    server = FastMCP("versioned")

    @server.tool(name="same", version="1.0")
    def same_v1() -> int:
        return 7

    @server.tool(name="same", version="2.0")
    def same_v2() -> int:
        return 8

    @server.tool(name="value", version="1.0")
    def value_v1() -> int:
        return 7

    @server.tool(name="value", version="2.0")
    def value_v2() -> str:
        return "hello"

    @server.tool(name="shape", version="1.0")
    def shape_v1() -> int:
        return 7

    @server.tool(name="shape", version="2.0")
    def shape_v2() -> dict:
        return {"a": 1}

    @server.tool(name="plain")
    def plain() -> dict:
        return {"a": 1}

    return server


async def test_pinned_call_with_different_output_type_returns_result(server):
    """The #5721 repro: v1 returns int, v2 returns str — pinning v1 must not
    raise 'Invalid structured content returned by tool value'."""
    async with Client(server) as client:
        result = await client.call_tool("value", version="1.0")
        assert result.data == 7
        assert result.structured_content == {"result": 7}


async def test_pinned_call_does_not_silently_lose_data(server):
    """Second #5721 manifestation: when the highest schema accepts the older
    version's JSON but the declared type differs, data must not be None."""
    async with Client(server) as client:
        result = await client.call_tool("shape", version="1.0")
        assert result.data == 7
        assert result.structured_content == {"result": 7}


async def test_pinned_call_with_same_output_type_still_works(server):
    async with Client(server) as client:
        result = await client.call_tool("same", version="1.0")
        assert result.data == 7


async def test_unpinned_call_still_validates_and_hydrates(server):
    """The schema path for unpinned calls is unchanged: highest version's
    schema hydrates data, and the pinned suppression restores the cache."""
    async with Client(server) as client:
        pinned = await client.call_tool("value", version="1.0")
        highest = await client.call_tool("value")
        assert pinned.data == 7
        assert highest.data == "hello"

        # The schema cache entry is restored after a pinned call.
        schema = client.session._tool_output_schemas.get("value")
        assert schema is not None
        assert schema.get("properties", {}).get("result", {}).get("type") == "string"

        plain = await client.call_tool("plain")
        assert plain.data == {"a": 1}


async def test_alternating_pinned_and_highest_calls(server):
    async with Client(server) as client:
        assert (await client.call_tool("value", version="1.0")).data == 7
        assert (await client.call_tool("value", version="2.0")).data == "hello"
        assert (await client.call_tool("value", version="1.0")).data == 7
        assert (await client.call_tool("value")).data == "hello"
