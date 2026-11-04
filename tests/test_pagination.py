from __future__ import annotations

from httpx import AsyncClient


async def _audit_page(
    client: AsyncClient,
    admin: dict,
    *,
    page: int,
    limit: int = 2,
    decision: str | None = None,
    as_of: str | None = None,
) -> tuple[list[dict], int, str]:
    params: dict[str, str | int] = {"limit": limit, "page": page}
    if decision is not None:
        params["decision"] = decision
    if as_of is not None:
        params["as_of"] = as_of
    response = await client.get(
        f"/v1/workspaces/{admin['workspace']}/audit",
        headers=admin["headers"],
        params=params,
    )
    assert response.status_code == 200, response.text
    total = int(response.headers["X-Total-Count"])
    assert response.headers["X-Page"] == str(page)
    assert response.headers["X-Page-Size"] == str(limit)
    return response.json(), total, response.headers["X-Snapshot"]


async def _trace_page(
    client: AsyncClient,
    admin: dict,
    *,
    page: int,
    limit: int = 4,
    as_of: str | None = None,
) -> tuple[list[dict], int, str]:
    params: dict[str, str | int] = {"limit": limit, "page": page}
    if as_of is not None:
        params["as_of"] = as_of
    response = await client.get(
        f"/v1/workspaces/{admin['workspace']}/traces",
        headers=admin["headers"],
        params=params,
    )
    assert response.status_code == 200, response.text
    return (
        response.json(),
        int(response.headers["X-Total-Count"]),
        response.headers["X-Snapshot"],
    )


async def _seed_audit_events(client: AsyncClient, admin: dict, count: int) -> None:
    for index in range(count):
        response = await client.post(
            f"/v1/workspaces/{admin['workspace']}/agents",
            headers=admin["headers"],
            json={
                "slug": f"paging-agent-{index}",
                "name": f"Paging Agent {index}",
                "issue_credential": False,
            },
        )
        assert response.status_code == 201, response.text


async def test_audit_numbered_pages_cover_every_event(client: AsyncClient, admin: dict):
    await _seed_audit_events(client, admin, 5)
    everything, total, snapshot = await _audit_page(client, admin, page=1, limit=200)
    assert total == len(everything)
    assert total >= 6

    collected: list[dict] = []
    for page in range(1, (total + 1) // 2 + 1):
        events, page_total, _ = await _audit_page(
            client, admin, page=page, limit=2, as_of=snapshot
        )
        assert page_total == total
        collected.extend(events)

    assert [event["id"] for event in collected] == [event["id"] for event in everything]
    timestamps = [event["created_at"] for event in collected]
    assert timestamps == sorted(timestamps, reverse=True)

    beyond, beyond_total, _ = await _audit_page(
        client, admin, page=(total + 1) // 2 + 2, limit=2, as_of=snapshot
    )
    assert beyond == []
    assert beyond_total == total


async def test_audit_since_filter_applies_to_total_and_pages(
    client: AsyncClient, admin: dict
):
    await _seed_audit_events(client, admin, 4)
    everything, _, _ = await _audit_page(client, admin, page=1, limit=200)
    cutoff = everything[len(everything) // 2]["created_at"]

    filtered: list[dict] = []
    total = 0
    page = 1
    snapshot: str | None = None
    while True:
        params = {"limit": 1, "page": page, "since": cutoff}
        if snapshot is not None:
            params["as_of"] = snapshot
        response = await client.get(
            f"/v1/workspaces/{admin['workspace']}/audit",
            headers=admin["headers"],
            params=params,
        )
        assert response.status_code == 200, response.text
        total = int(response.headers["X-Total-Count"])
        snapshot = response.headers["X-Snapshot"]
        events = response.json()
        if not events:
            break
        filtered.extend(events)
        page += 1

    expected = [event for event in everything if event["created_at"] >= cutoff]
    assert total == len(expected) == len(filtered)
    assert all(event["created_at"] >= cutoff for event in filtered)
    assert [event["id"] for event in filtered] == [event["id"] for event in expected]


async def test_trace_numbered_pages_do_not_overlap(client: AsyncClient, admin: dict):
    for _ in range(10):
        response = await client.get(
            f"/v1/workspaces/{admin['workspace']}/inventory",
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.text

    first, total, snapshot = await _trace_page(client, admin, page=1, limit=4)
    second, second_total, _ = await _trace_page(
        client, admin, page=2, limit=4, as_of=snapshot
    )
    assert len(first) == 4
    assert len(second) == 4
    assert total >= 10
    assert second_total == total
    first_ids = {trace["trace_id"] for trace in first}
    second_ids = {trace["trace_id"] for trace in second}
    assert first_ids.isdisjoint(second_ids)

    combined = first + second
    started = [trace["started_at"] for trace in combined]
    assert started == sorted(started, reverse=True)

    beyond, _, _ = await _trace_page(
        client, admin, page=(total + 3) // 4 + 2, limit=4, as_of=snapshot
    )
    assert beyond == []


async def test_page_zero_is_rejected(client: AsyncClient, admin: dict):
    for path in ("audit", "traces"):
        response = await client.get(
            f"/v1/workspaces/{admin['workspace']}/{path}",
            headers=admin["headers"],
            params={"page": 0, "limit": 10},
        )
        assert response.status_code == 400, response.text
