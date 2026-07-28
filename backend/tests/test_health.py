def test_health(client):
    r = client.get("/api/v1/meta/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_problem_json_shape(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404
