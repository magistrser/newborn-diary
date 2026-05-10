import uuid
from typing import Any

from fastapi.testclient import TestClient

async def test_create_and_list_event(application_client: TestClient) -> None:
    payload = {
        'type': 'feed_breast',
        'occurred_at': '2026-05-09T11:42:56Z',
        'payload': {'side': 'right'},
        'raw_text': 'Правая',
    }
    resp = application_client.post('/api/v1/events', json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data['type'] == 'feed_breast'
    assert data['payload']['side'] == 'right'
    event_id = data['id']

    resp2 = application_client.get('/api/v1/events', params={'from': '2026-05-09T00:00:00Z'})
    assert resp2.status_code == 200
    ids = [e['id'] for e in resp2.json()]
    assert event_id in ids


async def test_create_diaper_event(application_client: TestClient) -> None:
    payload = {
        'type': 'diaper',
        'occurred_at': '2026-05-09T13:07:48Z',
        'payload': {'kind': 'unknown'},
    }
    resp = application_client.post('/api/v1/events', json=payload)
    assert resp.status_code == 201
    assert resp.json()['payload']['kind'] == 'unknown'


async def test_create_sleep_start(application_client: TestClient) -> None:
    payload = {
        'type': 'sleep_start',
        'occurred_at': '2026-05-09T19:26:44Z',
        'payload': {},
    }
    resp = application_client.post('/api/v1/events', json=payload)
    assert resp.status_code == 201
    assert resp.json()['type'] == 'sleep_start'


def _create_event(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body = {
        'type': 'sleep_start',
        'occurred_at': '2026-05-10T08:00:00Z',
        'payload': {},
        **overrides,
    }
    resp = client.post('/api/v1/events', json=body)
    assert resp.status_code == 201
    return resp.json()


async def test_get_event_by_id(application_client: TestClient) -> None:
    created = _create_event(application_client)
    resp = application_client.get(f'/api/v1/events/{created["id"]}')
    assert resp.status_code == 200
    assert resp.json()['id'] == created['id']


async def test_get_event_not_found(application_client: TestClient) -> None:
    resp = application_client.get('/api/v1/events/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 404


async def test_patch_occurred_at_only(application_client: TestClient) -> None:
    created = _create_event(application_client)
    resp = application_client.patch(
        f'/api/v1/events/{created["id"]}',
        json={'occurred_at': '2026-05-10T09:30:00Z'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert '09:30' in data['occurred_at']
    assert data['type'] == 'sleep_start'


async def test_patch_type_and_payload(application_client: TestClient) -> None:
    created = _create_event(application_client)
    resp = application_client.patch(
        f'/api/v1/events/{created["id"]}',
        json={'type': 'diaper', 'payload': {'kind': 'pee'}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['type'] == 'diaper'
    assert data['payload']['kind'] == 'pee'


async def test_patch_invalid_payload_for_type(application_client: TestClient) -> None:
    created = _create_event(application_client)
    resp = application_client.patch(
        f'/api/v1/events/{created["id"]}',
        json={'type': 'feed_breast', 'payload': {}},  # missing required 'side'
    )
    assert resp.status_code == 422


async def test_patch_not_found(application_client: TestClient) -> None:
    resp = application_client.patch(
        '/api/v1/events/00000000-0000-0000-0000-000000000000',
        json={'occurred_at': '2026-05-10T10:00:00Z'},
    )
    assert resp.status_code == 404


async def test_delete_event(application_client: TestClient) -> None:
    created = _create_event(application_client)
    resp = application_client.delete(f'/api/v1/events/{created["id"]}')
    assert resp.status_code == 204

    resp2 = application_client.get(f'/api/v1/events/{created["id"]}')
    assert resp2.status_code == 404


async def test_delete_event_not_found(application_client: TestClient) -> None:
    resp = application_client.delete('/api/v1/events/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 404


# ── from-text idempotency ─────────────────────────────────────────────────────

async def test_from_text_returns_existing_events_without_parsing(
    from_text_client: tuple[TestClient, Any],
) -> None:
    """If events already exist for a (source_chat_id, source_message_id) pair,
    from-text must return them directly and must not invoke the LLM parser."""
    client, mock_parser = from_text_client
    mock_parser.reset_mock()

    chat_id = -9000111
    msg_id = f'idem-{uuid.uuid4().hex}'
    pre = client.post('/api/v1/events', json={
        'type': 'sleep_start',
        'occurred_at': '2026-05-10T10:00:00Z',
        'payload': {},
        'source_type': 'telegram_live',
        'source_chat_id': chat_id,
        'source_message_id': msg_id,
    })
    assert pre.status_code == 201, pre.text
    created_id = pre.json()['id']

    resp = client.post('/api/v1/events/from-text', json={
        'text': 'Заснул',
        'occurred_at': '2026-05-10T10:00:00Z',
        'source_type': 'telegram_live',
        'source_chat_id': chat_id,
        'source_message_id': msg_id,
    })

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data['events']) == 1
    assert data['events'][0]['id'] == created_id
    mock_parser.parse_message.assert_not_called()


async def test_from_text_returns_existing_events_from_different_source_type(
    from_text_client: tuple[TestClient, Any],
) -> None:
    """Events created via the importer (source_type='telegram_export') must be
    returned when the live bot processes the same (chat_id, message_id)."""
    client, mock_parser = from_text_client
    mock_parser.reset_mock()

    chat_id = -9000222
    msg_id = f'idem-{uuid.uuid4().hex}'
    pre = client.post('/api/v1/events', json={
        'type': 'walk',
        'occurred_at': '2026-05-10T11:00:00Z',
        'payload': {},
        'source_type': 'telegram_export',
        'source_chat_id': chat_id,
        'source_message_id': msg_id,
    })
    assert pre.status_code == 201, pre.text

    resp = client.post('/api/v1/events/from-text', json={
        'text': 'Прогулка',
        'occurred_at': '2026-05-10T11:00:00Z',
        'source_type': 'telegram_live',   # different source type — same physical message
        'source_chat_id': chat_id,
        'source_message_id': msg_id,
    })

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data['events']) == 1
    assert data['events'][0]['type'] == 'walk'
    mock_parser.parse_message.assert_not_called()


async def test_from_text_calls_parser_when_no_existing_events(
    from_text_client: tuple[TestClient, Any],
) -> None:
    """When no events exist for the source message, the LLM parser is called."""
    client, mock_parser = from_text_client
    mock_parser.reset_mock()

    resp = client.post('/api/v1/events/from-text', json={
        'text': 'Заснул',
        'occurred_at': '2026-05-10T12:00:00Z',
        'source_type': 'telegram_live',
        'source_chat_id': -9000333,
        'source_message_id': f'new-{uuid.uuid4().hex}',
    })
    assert resp.status_code == 201, resp.text

    mock_parser.parse_message.assert_called_once()


async def test_from_text_calls_parser_when_source_ids_absent(
    from_text_client: tuple[TestClient, Any],
) -> None:
    """Without source_chat_id / source_message_id the idempotency check is
    skipped and the parser is always called."""
    client, mock_parser = from_text_client
    mock_parser.reset_mock()

    resp = client.post('/api/v1/events/from-text', json={
        'text': 'Что-то',
        'occurred_at': '2026-05-10T13:00:00Z',
        'source_type': 'manual',
    })
    assert resp.status_code == 201, resp.text

    mock_parser.parse_message.assert_called_once()
