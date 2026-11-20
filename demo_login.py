"""The authentication this lab does NOT have.

Mặc định của demo: ai vào cũng là `guest`, và `guest` là hồ sơ hẹp nhất có trong hệ thống --
chỉ `catalog.search`, 12 lượt mỗi phút, không chi được đồng nào. Đó là toàn bộ "login" ở đây.

Có một chỗ để đăng nhập bằng mật khẩu, và nó cố tình trông thô:

    demo_login.issue("acme-web", "hunter2")   -> token cho merchant
    demo_login.issue_user("user-42")          -> grant cho một người dùng

Hai hàm này tồn tại để `demo.py` chạy được và để `tests/` khỏi phải giả lập một IdP. Chúng
KHÔNG phải một hệ tài khoản: không hash, không reset, không 2FA, không chống dò. Mật khẩu nằm
trong một dict trong file, ai đọc repo cũng thấy.

Chỗ để thay, khi có người mang hệ tài khoản thật tới -- và chỉ ba chỗ này:

1. `identity.principal_from_claims()`   nơi claims của bạn (OIDC, session, API key) thành Principal
2. `identity.exchange()`                chỗ cấp grant: redirect consent, hoặc assertion đã ký
3. `policy.PROFILES`                    thêm hồ sơ khi có vai mới; đừng sửa hồ sơ đang chạy

Ngoài ba chỗ đó, `gate.py` không biết gì về đăng nhập và không cần biết.
"""
from __future__ import annotations

from identity import mint

SECRET = b"test-secret-not-a-deployment-secret"

# Demo credentials. Plaintext, in the repository, on purpose: a fake that looks fake.
DEMO_PASSWORDS: dict[str, str] = {
    "acme-web": "hunter2",      # a merchant integration
    "pixon-ops": "ops-demo",    # an internal tool
}


def issue(client_id: str, password: str) -> str:
    """Password -> a client token. A stand-in, and it says so in its own docstring."""
    if DEMO_PASSWORDS.get(client_id) != password:
        raise PermissionError("unknown client or wrong password")
    tier = "internal" if client_id == "pixon-ops" else "partner"
    scopes = ["catalog:read", "orders:read", "charge:write"] if tier == "partner" else [
        "catalog:read", "orders:read", "users:read", "charge:write", "refund:write"]
    return mint(SECRET, client_id=client_id, tier=tier, scopes=scopes)


def issue_user(subject: str, client_id: str = "acme-web") -> str:
    """The user's own grant, as if they had just tapped 'đồng ý' on a consent screen."""
    return mint(SECRET, grant="user_mandate", sub=subject, client_id=client_id,
                scopes=["orders:read", "charge:write"])


def guest_token() -> str:
    """Nobody logged in. The default, and it is narrower than either logged-in tier."""
    return mint(SECRET, client_id="anonymous", tier="guest", scopes=["catalog:read"])
