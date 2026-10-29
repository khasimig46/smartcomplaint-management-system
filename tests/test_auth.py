import jwt

import services.auth as auth


def test_user_can_register(app):
    r = app.test_client().post("/auth/register", json={"name": "Asha", "email": "asha@test.com", "password": "password123"})
    assert r.status_code == 201
    assert r.get_json()["role"] == "citizen"
    assert "password_hash" not in r.get_json()


def test_password_is_hashed_with_bcrypt(app):
    app.test_client().post("/auth/register", json={"name": "A", "email": "a@test.com", "password": "password123"})
    stored = auth.load_users()[0]["password_hash"]
    assert stored != "password123" and stored.startswith("$2")


def test_duplicate_email_rejected(app):
    c = app.test_client()
    body = {"name": "A", "email": "dup@test.com", "password": "password123"}
    c.post("/auth/register", json=body)
    assert c.post("/auth/register", json=body).status_code == 409


def test_registration_validation(app):
    c = app.test_client()
    assert c.post("/auth/register", json={"name": "A", "email": "bad", "password": "password123"}).status_code == 400
    assert c.post("/auth/register", json={"name": "A", "email": "a@test.com", "password": "short"}).status_code == 400


def test_self_registration_cannot_pick_admin_role(app):
    r = app.test_client().post("/auth/register", json={"name": "A", "email": "x@test.com", "password": "password123", "role": "admin"})
    assert r.get_json()["role"] == "citizen"


def test_user_can_login_and_gets_jwt(app, make_user):
    make_user(email="c@test.com")
    r = app.test_client().post("/auth/login", json={"email": "c@test.com", "password": "password123"})
    assert r.status_code == 200
    payload = jwt.decode(r.get_json()["token"], "test-secret", algorithms=["HS256"])
    assert payload["role"] == "citizen"


def test_wrong_password_rejected(app, make_user):
    make_user(email="c@test.com")
    assert app.test_client().post("/auth/login", json={"email": "c@test.com", "password": "nope12345"}).status_code == 401


def test_jwt_authentication_works(app, make_user, login):
    make_user(email="c@test.com")
    c = app.test_client()
    assert c.get("/auth/me").status_code == 401
    assert c.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    r = c.get("/auth/me", headers=login("c@test.com"))
    assert r.status_code == 200 and r.get_json()["email"] == "c@test.com"


def test_role_permissions_enforced(app, make_user, login):
    make_user(email="cit@test.com")
    make_user("admin", email="adm@test.com")
    c = app.test_client()
    new_agent = {"name": "Ravi", "email": "ravi@test.com", "password": "password123", "role": "agent", "department": "Water Department"}
    assert c.post("/auth/users", json=new_agent, headers=login("cit@test.com")).status_code == 403
    r = c.post("/auth/users", json=new_agent, headers=login("adm@test.com"))
    assert r.status_code == 201 and r.get_json()["role"] == "agent"


def test_complaint_list_restricted_to_staff(app, make_user, login):
    make_user(email="cit@test.com")
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    assert c.get("/complaints").status_code == 401
    assert c.get("/complaints", headers=login("cit@test.com")).status_code == 403
    assert c.get("/complaints", headers=login("sup@test.com")).status_code == 200
