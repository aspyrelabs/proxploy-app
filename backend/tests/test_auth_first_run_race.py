"""PXP-37: concurrent first-run POST /users must mint exactly one owner.

Fires N unauthenticated create-user requests at once, all racing the
`db.query(User).count() == 0` check in create_user (proxploy/api/auth.py).
Without the lock, more than one thread can observe zero users and each
mints itself an owner account; with the lock, exactly one wins and every
other request lands after the first commit, so it hits the normal
"sign in again" 401 an unauthenticated non-first-run POST always gets.
"""

from concurrent.futures import ThreadPoolExecutor


def test_concurrent_first_run_posts_mint_only_one_owner(client, csrf_header):
    headers = csrf_header(client)
    n = 8

    def create(i):
        return client.post("/api/v1/users", json={
            "email": f"racer{i}@example.com",
            "password": "correct-horse-battery",
        }, headers=headers)

    with ThreadPoolExecutor(max_workers=n) as pool:
        responses = list(pool.map(create, range(n)))

    created = [r for r in responses if r.status_code == 201]
    assert len(created) == 1, (
        f"expected exactly one owner minted, got {len(created)}: "
        f"{[r.status_code for r in responses]}")
    assert created[0].json()["role"] == "owner"

    db = client.app.state.sessionmaker()
    try:
        from proxploy.models import User
        assert db.query(User).count() == 1
    finally:
        db.close()
