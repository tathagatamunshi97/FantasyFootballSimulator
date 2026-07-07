"""Diagnose Anindo login — do not commit."""
import sys
sys.path.insert(0, ".")

from web import auth

print("=== Password file keys ===")
print(list(auth._passwords.keys()))

print("\n=== team_has_password ===")
print("Anindo:", auth.team_has_password("Anindo"))

print("\n=== resolve_sheet_team (needs network) ===")
for name in ["Anindo", "anindo", "ANINDO", " anindo ", "Anindo's Team"]:
    try:
        resolved = auth.resolve_sheet_team(name)
        print(f"  {name!r} -> {resolved!r}")
    except Exception as exc:
        print(f"  {name!r} -> ERROR: {exc}")

print("\n=== attempt_login (wrong password) ===")
for name in ["Anindo", "anindo"]:
    r = auth.attempt_login(name, "wrongpassword123")
    print(f"  {name!r} -> {r}")

print("\n=== attempt_login unknown team ===")
r = auth.attempt_login("Anindo's Team", "test123456")
print(f"  Anindo's Team -> {r}")
