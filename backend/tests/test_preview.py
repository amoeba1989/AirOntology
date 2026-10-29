from fastapi.testclient import TestClient

from scripts.preview_memory import create_preview


def test_memory_preview_has_bounded_history_and_usable_ontology_questions(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', '')
    app = create_preview()
    with TestClient(app) as client:
        health = client.get('/api/health').json()
        assert health['preview'] and not health['mqtt']['connected'] and not health['fuseki']
        assert app.state.store.config.history_limit == 10
        situation = client.get('/api/situation').json()
        assert len(situation['targets']) == 4 and all(not t['stale'] for t in situation['targets'])
        response = client.post('/api/agent/ask', json={
            'question_id':'high_zone', 'position_id':situation['positions'][0]['id'], 'limit':10,
        })
        assert response.status_code == 200
        assert 'event: candidate' in response.text
        assert 'event: snapshot' in response.text and 'event: done' in response.text
