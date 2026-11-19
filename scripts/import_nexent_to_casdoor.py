# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Import one Nexent tenant's existing users and business groups into Casdoor."""

import argparse
import json
import os
import secrets
import stat
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ACTOR = "casdoor-account-import"
DEFAULT_ROLES = {"USER": "nexent-user", "DEV": "nexent-developer", "ADMIN": "nexent-admin"}


class ImportConflict(Exception):
    """An unsafe or ambiguous import input."""


def ordered_groups(groups, parents):
    """List groups after their parents, rejecting cycles and unsupported parents."""
    pending = dict(groups)
    resolved = set(parents)
    while pending:
        ready = [group for group in pending.values()
                 if group.parent_group_id is None or group.parent_group_id in resolved]
        if not ready:
            raise ImportConflict("An imported group has a cycle or a parent outside the business group directory")
        for group in ready:
            yield group
            resolved.add(group.group_id)
            pending.pop(group.group_id)


def read_journal(path, scope):
    """Read the private, target-scoped recovery file without displaying credentials."""
    if path is None or not path.exists():
        return None
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as handle:
        file = os.fstat(handle.fileno())
        if not stat.S_ISREG(file.st_mode) or stat.S_IMODE(file.st_mode) != 0o600 or file.st_uid != os.getuid():
            raise ImportConflict("The credentials file must be a regular file owned by the current user with mode 0600")
        journal = json.load(handle)
    if journal.get("scope") != scope:
        raise ImportConflict("The credentials file belongs to a different tenant or Casdoor instance")
    return journal


def create_journal(path, scope, accounts, groups, role_names):
    """Store random credentials durably before making any Casdoor request that writes."""
    journal = {"scope": scope, "batch": uuid4().hex, "users": {}, "groups": groups, "roles": role_names}
    for user_id, (email, role) in accounts.items():
        identity = uuid4()
        journal["users"][user_id] = {
            "email": email, "role": role, "username": f"nexent-{identity.hex}", "id": str(identity),
            "temporary_password": secrets.token_urlsafe(15) + "aA1!",
        }
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(journal, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return journal


def check_recovery_account(remote, saved, organization):
    if (remote.get("owner") != organization or remote.get("id") != saved["id"]
            or remote.get("name") != saved["username"] or remote.get("email") != saved["email"]
            or remote.get("needUpdatePassword") is not True or remote.get("isForbidden") is True
            or remote.get("isAdmin") is True or remote.get("isGlobalAdmin") is True):
        raise ImportConflict("A staged Casdoor account differs from its recovery record")


def verify_role(role, organization, name):
    if (not isinstance(role, dict) or role.get("owner") != organization or role.get("name") != name
            or role.get("isEnabled") is not True
            or not isinstance(role.get("users") or [], list)
            or not all(isinstance(member, str) for member in (role.get("users") or []))):
        raise ImportConflict(f"Casdoor role {name} is unavailable")


def mapped_role_name(role, mapping):
    names = [name for name, value in mapping.items() if value == role]
    if DEFAULT_ROLES[role] in names:
        return DEFAULT_ROLES[role]
    if len(names) == 1:
        return names[0]
    raise ImportConflict(f"Configure an unambiguous Casdoor role mapping for Nexent {role}")


def plan_import(session, tenant, organization, directory, client, journal):
    from sqlalchemy import func

    from management.db.configuration.models import TenantConfig
    from management.db.identity.models import TenantGroupInfo, TenantGroupUser, UserOAuthAccount, UserTenant
    from management.db.models import UserAccount

    default = session.query(TenantConfig.config_value).filter_by(
        tenant_id=tenant, config_key="DEFAULT_GROUP_ID", delete_flag="N",
    ).one_or_none()
    if not default or not str(default[0]).isdigit():
        raise ImportConflict("Set the Nexent tenant's default group before importing")
    groups = {row.group_id: row for row in session.query(TenantGroupInfo).filter_by(
        tenant_id=tenant, delete_flag="N",
    ).all()}
    default_id = int(default[0])
    if default_id not in groups:
        raise ImportConflict("The configured default group is missing")
    rows = session.query(UserAccount).join(UserTenant, UserTenant.user_id == UserAccount.user_id).filter(
        UserAccount.delete_flag == "N", UserTenant.tenant_id == tenant, UserTenant.delete_flag == "N",
    ).all()
    if not rows:
        raise ImportConflict("The Nexent tenant has no active accounts")

    remote_users = directory._directory_list(client, "get-users", organization)
    bound = directory._bound_users(session, tenant, remote_users)
    by_email = defaultdict(list)
    by_name = {row["name"]: row for row in remote_users}
    for row in remote_users:
        if row.get("email"):
            by_email[row["email"].strip().casefold()].append(row)

    local_ids = [row.user_id for row in rows]
    membership_counts = dict(session.query(UserTenant.user_id, func.count(UserTenant.user_tenant_id)).filter(
        UserTenant.user_id.in_(local_ids), UserTenant.delete_flag == "N",
    ).group_by(UserTenant.user_id).all())
    binding_ids = {user_id for user_id, in session.query(UserOAuthAccount.user_id).filter(
        UserOAuthAccount.user_id.in_(local_ids), UserOAuthAccount.provider == "casdoor",
        UserOAuthAccount.delete_flag == "N",
    )}
    accounts = {}
    skipped = 0
    staged = (journal or {}).get("users", {})
    for row in rows:
        if row.user_id in bound:
            continue
        if row.user_id in binding_ids:
            raise ImportConflict("An active Casdoor binding does not resolve in the target organization")
        email = (row.user_email or "").strip()
        if (not email or not row.password_login_enabled or row.user_role not in DEFAULT_ROLES
                or membership_counts.get(row.user_id) != 1 or (row.source_metadata or {}).get("api_only")):
            skipped += 1
            continue
        saved = staged.get(row.user_id)
        existing = by_name.get(saved["username"]) if saved else None
        if saved and (saved["email"], saved["role"]) != (email, row.user_role):
            raise ImportConflict("A staged Nexent account changed since the first run")
        if existing:
            detail = directory._request(client, "get-user", params={"id": f"{organization}/{saved['username']}"})
            check_recovery_account(detail, saved, organization)
        if any(not existing or found["id"] != existing["id"] for found in by_email[email.casefold()]):
            raise ImportConflict("A Casdoor email conflict requires explicit account linking before import")
        accounts[row.user_id] = (email, row.user_role)
    if len({email.casefold() for email, _ in accounts.values()}) != len(accounts):
        raise ImportConflict("The Nexent tenant has duplicate account emails")

    records = directory._parse_groups(directory._directory_list(client, "get-groups", organization), organization)
    scope = directory._scope(organization)
    shared = {}
    pending = {}
    for group_id, group in groups.items():
        if group_id == default_id:
            continue
        if group.casdoor_scope is None and group.casdoor_group_key is None:
            pending[group_id] = group
            continue
        name = (group.casdoor_group_key or "").split("/", 1)[0]
        if (group.casdoor_scope != scope or not records.get(name, {}).get("enabled")
                or records[name]["key"] != group.casdoor_group_key):
            raise ImportConflict(f"Nexent group {group_id} has an invalid or disabled Casdoor binding")
        shared[group_id] = name

    pending = list(ordered_groups(dict(sorted(pending.items())), shared))
    members = defaultdict(set)
    for group_id, user_id in session.query(TenantGroupUser.group_id, TenantGroupUser.user_id).filter(
        TenantGroupUser.group_id.in_([group.group_id for group in pending]), TenantGroupUser.delete_flag == "N",
    ):
        if user_id not in bound and user_id not in accounts:
            raise ImportConflict(f"Nexent group {group_id} contains a member who cannot be migrated")
        members[group_id].add(user_id)
    for group in pending:
        expected_name = f"nexent-import-{journal['batch']}-{group.group_id}" if journal else None
        if any(record["name"] == group.group_name and name != expected_name for name, record in records.items()):
            raise ImportConflict(f"Nexent group {group.group_id} conflicts with a Casdoor display name")
    return accounts, bound, pending, shared, members, skipped


def snapshot_groups(groups, members):
    return {str(group.group_id): [group.group_name, group.group_description,
                                 group.parent_group_id, sorted(members[group.group_id])]
            for group in groups}


def import_users(session, client, organization, tenant, accounts, users, journal, directory, role_names):
    from management.db.identity.models import UserOAuthAccount
    from management.services.permission.identity.casdoor import subject_key

    for user_id, (email, role) in accounts.items():
        saved = journal["users"][user_id]
        name = saved["username"]
        key = f"{organization}/{name}"
        user = directory._request(client, "get-user", params={"id": key})
        if user is None:
            directory._request(client, "add-user", payload={
                "owner": organization, "name": name, "id": saved["id"], "email": email,
                "displayName": email.split("@", 1)[0][:100],
                "password": saved["temporary_password"], "needUpdatePassword": True, "type": "normal-user",
            })
            user = directory._request(client, "get-user", params={"id": key})
        check_recovery_account(user or {}, saved, organization)
        role_name = role_names[role]
        role_id = f"{organization}/{role_name}"
        remote_role = directory._request(client, "get-role", params={"id": role_id})
        verify_role(remote_role, organization, role_name)
        members = remote_role.get("users") or []
        if key not in members:
            directory._request(client, "update-role", params={"id": role_id, "columns": "users"},
                               payload={**remote_role, "users": [*members, key]})
            updated = directory._request(client, "get-role", params={"id": role_id})
            verify_role(updated, organization, role_name)
            if set(updated.get("users") or []) != set(members) | {key}:
                raise ImportConflict("Casdoor role membership was not confirmed")
        session.add(UserOAuthAccount(
            user_id=user_id, provider="casdoor", provider_user_id=subject_key(user["id"]),
            provider_email=email, provider_username=name, tenant_id=tenant, created_by=ACTOR, updated_by=ACTOR,
        ))
        users[user_id] = user
    session.flush()


def import_groups(client, organization, groups, parents, members, users, journal, directory):
    rows = directory._directory_list(client, "get-groups", organization)
    records = directory._parse_groups(rows, organization)
    for group in groups:
        name = f"nexent-import-{journal['batch']}-{group.group_id}"
        parent = parents.get(group.parent_group_id)
        record = records.get(name)
        if record is None:
            directory._request(client, "add-group", payload={
                "owner": organization, "name": name, "displayName": group.group_name,
                "parentId": parent or organization, "isTopGroup": parent is None,
                "createdTime": datetime.now(timezone.utc).isoformat(), "type": "Virtual", "isEnabled": True,
                "properties": {"nexentDescription": group.group_description} if group.group_description is not None else {},
            })
            rows = directory._directory_list(client, "get-groups", organization)
            records = directory._parse_groups(rows, organization)
            record = records.get(name)
        if not record or (record["name"], record["parent"], record["description"], record["enabled"]) != (
            group.group_name, parent, group.group_description, True,
        ):
            raise ImportConflict(f"Casdoor did not confirm Nexent group {group.group_id}")
        for user_id in sorted(members[group.group_id]):
            directory._set_remote_membership(client, organization, f"{organization}/{name}", users[user_id], True)
        group.casdoor_scope = directory._scope(organization)
        group.casdoor_group_key = record["key"]
        group.updated_by = ACTOR
        parents[group.group_id] = name


def run(args):
    from consts import const as settings
    from contracts.constants import environment
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID
    from management.services.permission.identity import casdoor_groups as directory
    from management.services.permission.identity.casdoor_roles import parse_role_map

    if (args.tenant == ASSET_OWNER_TENANT_ID or args.tenant != environment.CASDOOR_GROUP_SYNC_TENANT_ID
            or args.organization == "built-in" or args.organization != settings.CASDOOR_ROLE_SYNC_ORGANIZATION):
        raise ImportConflict("Tenant and organization must match the configured business group sync target")
    if not all((environment.POSTGRES_HOST, environment.POSTGRES_PORT, environment.POSTGRES_DB,
                environment.POSTGRES_USER, environment.NEXENT_POSTGRES_PASSWORD)):
        raise ImportConflict("The PostgreSQL configuration is incomplete")
    if not environment.OAUTH_SSL_VERIFY:
        raise ImportConflict("Enable Casdoor TLS certificate verification before importing")
    if args.apply and (os.name != "posix" or not args.credentials_file):
        raise ImportConflict("--apply requires a POSIX host and --credentials-file")
    if args.credentials_file and os.name != "posix":
        raise ImportConflict("--credentials-file is supported on POSIX hosts")
    scope = [directory._scope(args.organization), args.tenant]
    role_map = parse_role_map(settings.CASDOOR_ROLE_MAP_JSON)
    with directory._directory(args.tenant) as (client, session, organization):
        journal = read_journal(args.credentials_file, scope)
        accounts, bound, groups, parents, members, skipped = plan_import(
            session, args.tenant, organization, directory, client, journal,
        )
        role_names = {role: mapped_role_name(role, role_map) for role in sorted({role for _, role in accounts.values()})}
        for name in role_names.values():
            remote = directory._request(client, "get-role", params={"id": f"{organization}/{name}"})
            verify_role(remote, organization, name)

        admins = sum(role == "ADMIN" for _, role in accounts.values())
        print(f"{'Apply' if args.apply else 'Dry run'} | tenant={args.tenant} organization={organization}")
        print(f"New users: {len(accounts)} ({admins} tenant administrators). Already linked: {len(bound)}. Skipped: {skipped}.")
        print(f"Business groups to import: {len(groups)}. Direct memberships: {sum(map(len, members.values()))}.")
        group_snapshot = snapshot_groups(groups, members)
        if journal and (accounts or groups) and (
            accounts.keys() != journal["users"].keys() or group_snapshot != journal["groups"]
            or role_names != journal["roles"]
        ):
            raise ImportConflict("The import inputs changed since this recovery file was created")
        if not args.apply or not (accounts or groups):
            return
        if journal is None:
            journal = create_journal(args.credentials_file, scope, accounts, group_snapshot, role_names)
        import_users(session, client, organization, args.tenant, accounts, bound, journal, directory, role_names)
        import_groups(client, organization, groups, parents, members, bound, journal, directory)
    print("Import committed. Distribute the temporary passwords privately from the credentials file.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True, help="Nexent Config environment file")
    parser.add_argument("--tenant", required=True, help="Nexent business tenant ID")
    parser.add_argument("--organization", required=True, help="Casdoor business organization name")
    parser.add_argument("--apply", action="store_true", help="Write accounts and groups. Default is preview.")
    parser.add_argument("--credentials-file", type=Path, help="Private recovery and temporary password JSON file")
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("--env-file must point to an existing Nexent environment file")
    load_dotenv(args.env_file, override=False)
    try:
        run(args)
    except ImportConflict as exc:
        print(f"Import stopped: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Import stopped ({type(exc).__name__}). Check service logs and retain the recovery file.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
