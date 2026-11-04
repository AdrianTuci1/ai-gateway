from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, AsyncIterator, Iterable, Sequence

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from sqlalchemy import Boolean, DateTime, Integer, JSON, LargeBinary, Uuid, inspect

from agw.config import Settings
from agw.core.errors import ApiError
from agw.core.roles import seed_builtin_roles
from agw.core.time import utcnow
from agw.db.models import (
    Agent,
    AgentCredential,
    AgentGrant,
    AppUser,
    AuditEvent,
    BootstrapState,
    EnrollmentDeviceCode,
    EnrollmentToken,
    Identity,
    IdentityInvite,
    Membership,
    ResourceGroup,
    RoleDefinition,
    ServiceConnection,
    ServiceTool,
    SignupRequest,
    TraceSpan,
    UpstreamService,
    Workspace,
)
from agw.store.base import Store

# Key layout. Every alternate lookup (slug, name, prefix, email) is a
# strongly consistent link item, so a write followed by a read in the next
# request cannot miss because of GSI replication lag.
WS_PK = "WORKSPACE#{id}"
WS_SLUG_PK = "LOOKUP#WORKSPACE#{slug}"
WORKSPACES_PK = "WORKSPACES"
USER_PK = "USER#{id}"
USER_EMAIL_PK = "LOOKUP#USEREMAIL#{email}"
USER_SUBJECT_PK = "LOOKUP#SUBJECT#{subject}"
USER_MEMBERSHIPS_PK = "USERMEMBERSHIPS#{user_id}"
ROLE_PK = "ROLE#{id}"
ROLE_LOOKUP_PK = "LOOKUP#ROLE#{scope}#{name}"
GLOBAL_ROLES_PK = "GLOBALROLES"
MEMBERSHIP_PK = "MEMBERSHIP#{workspace_id}#{principal_type}#{principal_id}"
WS_MEMBERS_PK = "WSMEMBERS#{workspace_id}"
SIGNUP_PK = "SIGNUP#{id}"
WS_SIGNUPS_PK = "WSSIGNUPS#{workspace_id}"
IDENTITY_PK = "IDENTITY#{id}"
WS_IDENTITIES_PK = "WSIDENTITIES#{workspace_id}"
IDENTITY_MEMBERS_PK = "IDENTITYMEMBERS#{identity_id}"
INVITE_PK = "INVITE#{id}"
INVITE_HASH_PK = "LOOKUP#INVITEHASH#{hash}"
GROUP_PK = "GROUP#{id}"
WS_GROUPS_PK = "WSGROUPS#{workspace_id}"
TRACE_PK = "TRACE#{trace_id}"
WS_TRACES_PK = "WSTRACES#{workspace_id}"
BOOTSTRAP_PK = "STATE#BOOTSTRAP"
HEALTH_PK = "STATE#HEALTH"
AGENT_PK = "AGENT#{id}"
AGENT_SLUG_PK = "LOOKUP#AGENT#{workspace_id}#{slug}"
WS_AGENTS_PK = "WSAGENTS#{workspace_id}"
CREDENTIAL_PREFIX_PK = "LOOKUP#CREDPREFIX#{prefix}"
SERVICE_PK = "SERVICE#{id}"
SERVICE_NAME_PK = "LOOKUP#SERVICE#{workspace_id}#{name}"
WS_SERVICES_PK = "WSSERVICES#{workspace_id}"
SERVICE_GRANTS_PK = "SERVICEGRANTS#{service_id}"
CONNECTION_PK = "CONNECTION#{id}"
CONNECTION_BINDING_PK = "LOOKUP#BINDING#{binding_key}"
AGENT_CONNECTIONS_PK = "AGENTCONNECTIONS#{agent_id}"
ENROLLMENT_PK = "ENROLL#{id}"
ENROLLMENT_PREFIX_PK = "LOOKUP#ENROLLPREFIX#{prefix}"
DEVICE_PK = "DEVICE#{id}"
DEVICE_USER_CODE_PK = "LOOKUP#USERCODE#{user_code}"
DEVICE_HASH_PK = "LOOKUP#DEVHASH#{digest}"
AUDIT_PK = "AUDIT#{workspace_id}"

META = "#META"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _to_bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    inner = getattr(value, "value", None)
    if isinstance(inner, (bytes, bytearray)):
        return bytes(inner)
    return bytes(value)


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str), parse_float=Decimal)


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_from_dynamo(entry) for entry in value]
    if isinstance(value, dict):
        return {key: _from_dynamo(entry) for key, entry in value.items()}
    return value


@lru_cache(maxsize=None)
def _columns(model: type) -> dict[str, Any]:
    # Map attribute names (not column names) so renamed columns such as
    # AuditEvent.meta / "metadata" round-trip through the model constructor.
    return {
        attribute.key: attribute.columns[0]
        for attribute in inspect(model).column_attrs
    }


def _dump(obj: Any) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, column in _columns(type(obj)).items():
        value = getattr(obj, key)
        if isinstance(column.type, Uuid):
            item[key] = str(value) if value is not None else None
        elif isinstance(column.type, DateTime):
            item[key] = _iso(value)
        elif isinstance(column.type, LargeBinary):
            item[key] = _to_bytes(value)
        elif isinstance(column.type, JSON):
            item[key] = _jsonable(value) if value is not None else {}
        elif isinstance(column.type, Boolean):
            item[key] = bool(value) if value is not None else None
        elif isinstance(column.type, Integer):
            item[key] = int(value) if value is not None else None
        else:
            item[key] = value
    if item.get("expires_at"):
        expiry = _parse_iso(item["expires_at"])
        if expiry is not None:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            item["expires_at_epoch"] = int(expiry.timestamp())
    return item


def _load(model: type, item: dict[str, Any]) -> Any:
    values: dict[str, Any] = {}
    for key, column in _columns(model).items():
        raw = item.get(key)
        if isinstance(column.type, Uuid):
            values[key] = uuid.UUID(raw) if raw else None
        elif isinstance(column.type, DateTime):
            values[key] = _parse_iso(raw)
        elif isinstance(column.type, LargeBinary):
            values[key] = _to_bytes(raw)
        elif isinstance(column.type, JSON):
            values[key] = _from_dynamo(raw) if raw is not None else {}
        elif isinstance(column.type, Boolean):
            values[key] = bool(raw) if raw is not None else None
        elif isinstance(column.type, Integer):
            values[key] = int(raw) if raw is not None else None
        else:
            values[key] = raw
    return model(**values)


def _condition_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", {}) or {}
    code = response.get("Error", {}).get("Code")
    if code == "ConditionalCheckFailedException":
        return True
    if code == "TransactionCanceledException":
        reasons = response.get("CancellationReasons") or []
        return any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons)
    return False


class DynamoStore:
    def __init__(self, client: Any, table: str) -> None:
        self.client = client
        self.table = table
        self._serializer = TypeSerializer()
        self._deserializer = TypeDeserializer()

    # low level helpers

    async def _call(self, method: Any, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(method, **kwargs)

    def _encode_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._serializer.serialize(value) for key, value in item.items()
        }

    def _decode_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._deserializer.deserialize(value)
            for key, value in item.items()
        }

    def _encode_values(
        self, values: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not values:
            return None
        return {
            key: self._serializer.serialize(value) for key, value in values.items()
        }

    async def _put(
        self,
        item: dict[str, Any],
        *,
        condition: str | None = None,
        names: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "Item": self._encode_item(item),
        }
        if condition:
            kwargs["ConditionExpression"] = condition
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if values:
            kwargs["ExpressionAttributeValues"] = self._encode_values(values)
        await self._call(self.client.put_item, **kwargs)

    async def _get(
        self, pk: str, sk: str = META, *, consistent: bool = True
    ) -> dict[str, Any] | None:
        response = await self._call(
            self.client.get_item,
            TableName=self.table,
            Key=self._encode_item({"pk": pk, "sk": sk}),
            ConsistentRead=consistent,
        )
        item = response.get("Item")
        return self._decode_item(item) if item else None

    async def _link(self, pk: str) -> dict[str, Any] | None:
        return await self._get(pk)

    async def _target(self, pk: str) -> uuid.UUID | None:
        item = await self._link(pk)
        if item is None or not item.get("target_id"):
            return None
        return uuid.UUID(item["target_id"])

    async def _query(
        self,
        pk: str,
        *,
        sk_prefix: str | None = None,
        sk_from: str | None = None,
        sk_before: str | None = None,
        descending: bool = False,
        limit: int | None = None,
        offset: int = 0,
        projection: str | None = None,
        names: dict[str, str] | None = None,
        filter_expression: str | None = None,
        values: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raw_values: dict[str, Any] = {":pk": pk}
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "KeyConditionExpression": "pk = :pk",
            "ConsistentRead": True,
        }
        if sk_prefix is not None:
            kwargs["KeyConditionExpression"] += " AND begins_with(sk, :sk)"
            raw_values[":sk"] = sk_prefix
        if sk_from is not None:
            kwargs["KeyConditionExpression"] += " AND sk >= :sk_from"
            raw_values[":sk_from"] = sk_from
        if sk_before is not None:
            kwargs["KeyConditionExpression"] += " AND sk < :sk_before"
            raw_values[":sk_before"] = sk_before
        if descending:
            kwargs["ScanIndexForward"] = False
        # DynamoDB applies Limit before FilterExpression, so a filtered query
        # would return fewer matches than asked for. Page it out instead.
        if limit is not None and filter_expression is None:
            kwargs["Limit"] = offset + limit
        if projection is not None:
            kwargs["ProjectionExpression"] = projection
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if filter_expression:
            kwargs["FilterExpression"] = filter_expression
        if values:
            raw_values.update(values)
        kwargs["ExpressionAttributeValues"] = self._encode_values(raw_values)

        items: list[dict[str, Any]] = []
        while True:
            response = await self._call(self.client.query, **kwargs)
            items.extend(
                self._decode_item(item) for item in response.get("Items", [])
            )
            last = response.get("LastEvaluatedKey")
            if limit is not None and len(items) >= offset + limit:
                return items[offset : offset + limit]
            if not last:
                return items[offset : offset + limit] if limit is not None else items[offset:]
            kwargs["ExclusiveStartKey"] = last

    async def _count(
        self,
        pk: str,
        *,
        sk_from: str | None = None,
        sk_before: str | None = None,
        filter_expression: str | None = None,
        names: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
    ) -> int:
        raw_values: dict[str, Any] = {":pk": pk}
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "KeyConditionExpression": "pk = :pk",
            "ConsistentRead": True,
            "Select": "COUNT",
        }
        if sk_from is not None:
            kwargs["KeyConditionExpression"] += " AND sk >= :sk_from"
            raw_values[":sk_from"] = sk_from
        if sk_before is not None:
            kwargs["KeyConditionExpression"] += " AND sk < :sk_before"
            raw_values[":sk_before"] = sk_before
        if filter_expression:
            kwargs["FilterExpression"] = filter_expression
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if values:
            raw_values.update(values)
        kwargs["ExpressionAttributeValues"] = self._encode_values(raw_values)

        total = 0
        while True:
            response = await self._call(self.client.query, **kwargs)
            total += int(response.get("Count", 0))
            last = response.get("LastEvaluatedKey")
            if not last:
                return total
            kwargs["ExclusiveStartKey"] = last

    async def _batch_get(
        self,
        keys: Iterable[tuple[str, str]],
        *,
        consistent: bool = True,
    ) -> list[dict[str, Any]]:
        pending = [
            self._encode_item({"pk": pk, "sk": sk}) for pk, sk in keys
        ]
        if not pending:
            return []
        found: list[dict[str, Any]] = []
        while pending:
            chunk, pending = pending[:100], pending[100:]
            request: dict[str, Any] = {self.table: {"Keys": chunk}}
            if consistent:
                request[self.table]["ConsistentRead"] = True
            while True:
                response = await self._call(
                    self.client.batch_get_item, RequestItems=request
                )
                found.extend(
                    self._decode_item(item)
                    for item in response.get("Responses", {}).get(self.table, [])
                )
                unprocessed = response.get("UnprocessedKeys") or {}
                if not unprocessed or not unprocessed.get(self.table, {}).get("Keys"):
                    break
                request = {self.table: unprocessed[self.table]}
        return found

    def _encode_transaction(
        self, items: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        encoded: list[dict[str, Any]] = []
        for entry in items:
            operation, payload = next(iter(entry.items()))
            payload = dict(payload)
            if "Item" in payload:
                payload["Item"] = self._encode_item(payload["Item"])
            if "Key" in payload:
                payload["Key"] = self._encode_item(payload["Key"])
            if "ExpressionAttributeValues" in payload:
                payload["ExpressionAttributeValues"] = self._encode_values(
                    payload["ExpressionAttributeValues"]
                )
            encoded.append({operation: payload})
        return encoded

    async def _transact(self, items: Sequence[dict[str, Any]]) -> None:
        await self._call(
            self.client.transact_write_items,
            TransactItems=self._encode_transaction(items),
        )

    async def _update(
        self,
        pk: str,
        sk: str,
        expression: str,
        *,
        values: dict[str, Any],
        names: dict[str, str] | None = None,
        condition: str | None = None,
        condition_values: dict[str, Any] | None = None,
    ) -> bool:
        raw_values = dict(values)
        if condition:
            raw_values.update(condition_values or {})
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "Key": self._encode_item({"pk": pk, "sk": sk}),
            "UpdateExpression": expression,
            "ExpressionAttributeValues": self._encode_values(raw_values),
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if condition:
            kwargs["ConditionExpression"] = condition
        try:
            await self._call(self.client.update_item, **kwargs)
            return True
        except Exception as exc:  # noqa: BLE001 - boto3 raises ClientError
            if _condition_failed(exc):
                return False
            raise

    # Store interface

    async def ping(self) -> None:
        await self._get(HEALTH_PK, consistent=True)

    async def commit(self) -> None:
        return None

    # workspaces

    async def count_workspaces(self) -> int:
        rows = await self._query(WORKSPACES_PK, projection="sk")
        return len(rows)

    async def create_workspace(self, *, slug: str, name: str) -> Workspace:
        workspace = Workspace(
            id=uuid.uuid4(), slug=slug, name=name, created_at=utcnow()
        )
        item = _dump(workspace)
        item["pk"], item["sk"] = WS_PK.format(id=workspace.id), META
        try:
            await self._transact(
                [
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": WS_SLUG_PK.format(slug=slug),
                                "sk": META,
                                "target_id": str(workspace.id),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": WORKSPACES_PK,
                                "sk": str(workspace.id),
                            },
                        }
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "workspace slug already exists") from exc
            raise
        return workspace

    async def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None:
        item = await self._get(WS_PK.format(id=workspace_id))
        return _load(Workspace, item) if item else None

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        target = await self._target(WS_SLUG_PK.format(slug=slug))
        return await self.get_workspace(target) if target else None

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        links = await self._query(USER_MEMBERSHIPS_PK.format(user_id=user_id))
        keys = [(WS_PK.format(id=uuid.UUID(link["sk"])), META) for link in links]
        workspaces = [
            _load(Workspace, item)
            for item in await self._batch_get(keys)
            if item.get("deleted_at") is None
        ]
        return sorted(workspaces, key=lambda entry: entry.created_at)

    # identities

    async def create_identity(
        self, *, workspace_id: uuid.UUID, name: str, status: str = "pending"
    ) -> Identity:
        identity = Identity(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name=name,
            status=status,
            created_at=utcnow(),
        )
        item = self._identity_item(identity)
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": item}},
                {"Put": {"TableName": self.table, "Item": self._identity_link(identity)}},
            ]
        )
        return identity

    async def get_identity(self, identity_id: uuid.UUID) -> Identity | None:
        item = await self._get(IDENTITY_PK.format(id=identity_id))
        return _load(Identity, item) if item else None

    async def list_identities(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[Identity]:
        links = await self._query(
            WS_IDENTITIES_PK.format(workspace_id=workspace_id), descending=True
        )
        if status is not None:
            links = [link for link in links if link.get("status") == status]
        keys = [
            (IDENTITY_PK.format(id=link["target_id"]), META) for link in links
        ]
        found = await self._batch_get(keys)
        identities = [_load(Identity, item) for item in found]
        return sorted(
            identities,
            key=lambda entry: (entry.created_at, str(entry.id)),
            reverse=True,
        )

    async def save_identity(self, identity: Identity) -> None:
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": self._identity_item(identity)}},
                {"Put": {"TableName": self.table, "Item": self._identity_link(identity)}},
            ]
        )

    async def list_memberships_for_identity(
        self, identity_id: uuid.UUID
    ) -> list[Membership]:
        items = await self._query(
            IDENTITY_MEMBERS_PK.format(identity_id=identity_id)
        )
        return [_load(Membership, item) for item in items]

    async def create_identity_invite(
        self,
        *,
        identity_id: uuid.UUID,
        workspace_id: uuid.UUID,
        email: str,
        role_id: uuid.UUID,
        token_hash: bytes,
        created_by: uuid.UUID | None,
        expires_at: datetime,
    ) -> IdentityInvite:
        invite = IdentityInvite(
            id=uuid.uuid4(),
            identity_id=identity_id,
            workspace_id=workspace_id,
            email=email,
            role_id=role_id,
            token_hash=token_hash,
            created_by=created_by,
            expires_at=expires_at,
            created_at=utcnow(),
        )
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": self._invite_item(invite)}},
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": INVITE_HASH_PK.format(hash=token_hash.hex()),
                            "sk": META,
                            "target_id": str(invite.id),
                        },
                    }
                },
            ]
        )
        return invite

    async def get_identity_invite_by_hash(
        self, token_hash: bytes
    ) -> IdentityInvite | None:
        target = await self._target(INVITE_HASH_PK.format(hash=token_hash.hex()))
        if target is None:
            return None
        item = await self._get(INVITE_PK.format(id=target))
        return _load(IdentityInvite, item) if item else None

    async def save_identity_invite(self, invite: IdentityInvite) -> None:
        await self._put(self._invite_item(invite))

    def _identity_item(self, identity: Identity) -> dict[str, Any]:
        item = _dump(identity)
        item["pk"], item["sk"] = IDENTITY_PK.format(id=identity.id), META
        return item

    def _identity_link(self, identity: Identity) -> dict[str, Any]:
        return {
            "pk": WS_IDENTITIES_PK.format(workspace_id=identity.workspace_id),
            "sk": f"{_iso(identity.created_at)}#{identity.id}",
            "target_id": str(identity.id),
            "status": identity.status,
        }

    def _invite_item(self, invite: IdentityInvite) -> dict[str, Any]:
        item = _dump(invite)
        item["pk"], item["sk"] = INVITE_PK.format(id=invite.id), META
        return item

    # users

    async def create_user(
        self, *, email: str, idp_subject: str, display_name: str | None = None
    ) -> AppUser:
        user = AppUser(
            id=uuid.uuid4(),
            email=email,
            idp_subject=idp_subject,
            display_name=display_name,
            created_at=utcnow(),
        )
        item = _dump(user)
        item["pk"], item["sk"] = USER_PK.format(id=user.id), META
        try:
            await self._transact(
                [
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": USER_EMAIL_PK.format(email=email.lower()),
                                "sk": META,
                                "target_id": str(user.id),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": USER_SUBJECT_PK.format(subject=idp_subject),
                                "sk": META,
                                "target_id": str(user.id),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "user already exists") from exc
            raise
        return user

    async def get_user(self, user_id: uuid.UUID) -> AppUser | None:
        item = await self._get(USER_PK.format(id=user_id))
        return _load(AppUser, item) if item else None

    async def get_user_by_email(self, email: str) -> AppUser | None:
        target = await self._target(USER_EMAIL_PK.format(email=email.lower()))
        return await self.get_user(target) if target else None

    async def get_user_by_subject(self, subject: str) -> AppUser | None:
        target = await self._target(USER_SUBJECT_PK.format(subject=subject))
        return await self.get_user(target) if target else None

    async def save_user(self, user: AppUser) -> None:
        item = _dump(user)
        item["pk"], item["sk"] = USER_PK.format(id=user.id), META
        await self._put(item)

    async def touch_user(self, user: AppUser, when: datetime) -> None:
        await self._update(
            USER_PK.format(id=user.id),
            META,
            "SET last_seen_at = :when",
            values={":when": _iso(when)},
            condition="attribute_exists(pk)",
        )

    # roles

    async def get_role(self, role_id: uuid.UUID) -> RoleDefinition | None:
        item = await self._get(ROLE_PK.format(id=role_id))
        return _load(RoleDefinition, item) if item else None

    async def get_builtin_role(self, name: str) -> RoleDefinition:
        target = await self._target(
            ROLE_LOOKUP_PK.format(scope="GLOBAL", name=name)
        )
        role = await self.get_role(target) if target else None
        if role is None:
            raise LookupError(f"unknown builtin role: {name}")
        return role

    async def resolve_role(
        self, workspace_id: uuid.UUID, name: str
    ) -> RoleDefinition | None:
        for scope in (str(workspace_id), "GLOBAL"):
            target = await self._target(
                ROLE_LOOKUP_PK.format(scope=scope, name=name)
            )
            if target:
                role = await self.get_role(target)
                if role is not None:
                    return role
        return None

    async def list_global_roles(self) -> list[RoleDefinition]:
        links = await self._query(GLOBAL_ROLES_PK, projection="sk")
        keys = [(ROLE_PK.format(id=uuid.UUID(link["sk"])), META) for link in links]
        return [_load(RoleDefinition, item) for item in await self._batch_get(keys)]

    async def create_role(
        self,
        *,
        workspace_id: uuid.UUID | None,
        name: str,
        permissions: Sequence[str],
        is_builtin: bool,
    ) -> RoleDefinition:
        role = RoleDefinition(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name=name,
            permissions=list(permissions),
            is_builtin=is_builtin,
        )
        item = _dump(role)
        item["pk"], item["sk"] = ROLE_PK.format(id=role.id), META
        scope = str(workspace_id) if workspace_id else "GLOBAL"
        items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self.table,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {
                "Put": {
                    "TableName": self.table,
                    "Item": {
                        "pk": ROLE_LOOKUP_PK.format(scope=scope, name=name),
                        "sk": META,
                        "target_id": str(role.id),
                    },
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
        ]
        if workspace_id is None:
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {"pk": GLOBAL_ROLES_PK, "sk": str(role.id)},
                    }
                }
            )
        try:
            await self._transact(items)
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                existing = await self.get_builtin_role(name) if workspace_id is None else None
                if existing is not None:
                    return existing
                raise ApiError(
                    409, "conflict", f"role already exists: {name}"
                ) from exc
            raise
        return role

    async def update_role_permissions(
        self, role: RoleDefinition, permissions: Sequence[str]
    ) -> None:
        await self._update(
            ROLE_PK.format(id=role.id),
            META,
            "SET permissions = :permissions",
            values={":permissions": _jsonable(list(permissions))},
        )

    # memberships

    async def get_membership(
        self, workspace_id: uuid.UUID, principal_type: str, principal_id: uuid.UUID
    ) -> Membership | None:
        item = await self._get(
            MEMBERSHIP_PK.format(
                workspace_id=workspace_id,
                principal_type=principal_type,
                principal_id=principal_id,
            )
        )
        return _load(Membership, item) if item else None

    async def create_membership(
        self,
        *,
        workspace_id: uuid.UUID,
        principal_type: str,
        principal_id: uuid.UUID,
        role_id: uuid.UUID,
        status: str = "active",
        identity_id: uuid.UUID | None = None,
        is_identity_admin: bool = False,
    ) -> Membership:
        membership = Membership(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            principal_type=principal_type,
            principal_id=principal_id,
            role_id=role_id,
            status=status,
            identity_id=identity_id,
            is_identity_admin=is_identity_admin,
            created_at=utcnow(),
        )
        item = _dump(membership)
        item["pk"], item["sk"] = (
            MEMBERSHIP_PK.format(
                workspace_id=workspace_id,
                principal_type=principal_type,
                principal_id=principal_id,
            ),
            META,
        )
        items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self.table,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            },
            {
                "Put": {
                    "TableName": self.table,
                    "Item": {
                        **item,
                        "pk": WS_MEMBERS_PK.format(workspace_id=workspace_id),
                        "sk": f"{principal_type}#{principal_id}",
                    },
                }
            },
        ]
        if principal_type == "user":
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": USER_MEMBERSHIPS_PK.format(user_id=principal_id),
                            "sk": str(workspace_id),
                        },
                    }
                }
            )
        if identity_id is not None:
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            **item,
                            "pk": IDENTITY_MEMBERS_PK.format(identity_id=identity_id),
                            "sk": f"{principal_type}#{principal_id}",
                        },
                    }
                }
            )
        try:
            await self._transact(items)
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "membership already exists") from exc
            raise
        return membership

    async def set_membership_role(
        self, membership: Membership, role_id: uuid.UUID
    ) -> None:
        await self._update(
            MEMBERSHIP_PK.format(
                workspace_id=membership.workspace_id,
                principal_type=membership.principal_type,
                principal_id=membership.principal_id,
            ),
            META,
            "SET role_id = :role_id",
            values={":role_id": str(role_id)},
        )
        await self._update(
            WS_MEMBERS_PK.format(workspace_id=membership.workspace_id),
            f"{membership.principal_type}#{membership.principal_id}",
            "SET role_id = :role_id",
            values={":role_id": str(role_id)},
            condition="attribute_exists(pk)",
        )

    async def list_memberships(self, workspace_id: uuid.UUID) -> list[Membership]:
        items = await self._query(WS_MEMBERS_PK.format(workspace_id=workspace_id))
        return [_load(Membership, item) for item in items]

    async def save_membership(self, membership: Membership) -> None:
        item = _dump(membership)
        item["pk"], item["sk"] = (
            MEMBERSHIP_PK.format(
                workspace_id=membership.workspace_id,
                principal_type=membership.principal_type,
                principal_id=membership.principal_id,
            ),
            META,
        )
        items: list[dict[str, Any]] = [
            {"Put": {"TableName": self.table, "Item": item}},
            {
                "Put": {
                    "TableName": self.table,
                    "Item": {
                        **item,
                        "pk": WS_MEMBERS_PK.format(
                            workspace_id=membership.workspace_id
                        ),
                        "sk": f"{membership.principal_type}#{membership.principal_id}",
                    },
                }
            },
        ]
        if membership.identity_id is not None:
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            **item,
                            "pk": IDENTITY_MEMBERS_PK.format(
                                identity_id=membership.identity_id
                            ),
                            "sk": f"{membership.principal_type}#{membership.principal_id}",
                        },
                    }
                }
            )
        await self._transact(items)

    # signup requests

    async def create_signup_request(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: str,
        email: str | None,
        display_name: str | None,
        agent_name: str | None,
        agent_slug: str | None,
        requested_role: str | None,
        message: str | None,
        identity_id: uuid.UUID | None = None,
        identity_name: str | None = None,
        owner_email: str | None = None,
    ) -> SignupRequest:
        signup = SignupRequest(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            kind=kind,
            status="pending",
            identity_id=identity_id,
            identity_name=identity_name,
            email=email,
            owner_email=owner_email,
            display_name=display_name,
            agent_name=agent_name,
            agent_slug=agent_slug,
            requested_role=requested_role,
            message=message,
            created_at=utcnow(),
        )
        item = self._signup_item(signup)
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": item}},
                {"Put": {"TableName": self.table, "Item": self._signup_link(signup)}},
            ]
        )
        return signup

    async def get_signup_request(
        self, request_id: uuid.UUID
    ) -> SignupRequest | None:
        item = await self._get(SIGNUP_PK.format(id=request_id))
        return _load(SignupRequest, item) if item else None

    async def list_signup_requests(
        self, workspace_id: uuid.UUID, *, status: str | None = None
    ) -> list[SignupRequest]:
        links = await self._query(
            WS_SIGNUPS_PK.format(workspace_id=workspace_id), descending=True
        )
        if status is not None:
            links = [link for link in links if link.get("status") == status]
        keys = [
            (SIGNUP_PK.format(id=link["target_id"]), META) for link in links
        ]
        found = await self._batch_get(keys)
        requests = [_load(SignupRequest, item) for item in found]
        return sorted(
            requests,
            key=lambda entry: (entry.created_at, str(entry.id)),
            reverse=True,
        )

    async def save_signup_request(self, signup: SignupRequest) -> None:
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": self._signup_item(signup)}},
                {"Put": {"TableName": self.table, "Item": self._signup_link(signup)}},
            ]
        )

    def _signup_item(self, signup: SignupRequest) -> dict[str, Any]:
        item = _dump(signup)
        item["pk"], item["sk"] = SIGNUP_PK.format(id=signup.id), META
        return item

    def _signup_link(self, signup: SignupRequest) -> dict[str, Any]:
        return {
            "pk": WS_SIGNUPS_PK.format(workspace_id=signup.workspace_id),
            "sk": f"{_iso(signup.created_at)}#{signup.id}",
            "target_id": str(signup.id),
            "status": signup.status,
            "kind": signup.kind,
        }

    # resource groups

    async def create_resource_group(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        kind: str,
        description: str | None,
    ) -> ResourceGroup:
        group = ResourceGroup(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            description=description,
            created_at=utcnow(),
        )
        item = _dump(group)
        item["pk"], item["sk"] = GROUP_PK.format(id=group.id), META
        pointer = {
            **item,
            "pk": WS_GROUPS_PK.format(workspace_id=workspace_id),
            "sk": f"GROUP#{group.id}",
        }
        try:
            await self._transact(
                [
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": pointer,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "resource group already exists") from exc
            raise
        return group

    async def get_resource_group(
        self, group_id: uuid.UUID
    ) -> ResourceGroup | None:
        item = await self._get(GROUP_PK.format(id=group_id))
        return _load(ResourceGroup, item) if item else None

    async def list_resource_groups(
        self, workspace_id: uuid.UUID
    ) -> list[ResourceGroup]:
        items = await self._query(WS_GROUPS_PK.format(workspace_id=workspace_id))
        groups = [_load(ResourceGroup, item) for item in items]
        return sorted(groups, key=lambda group: group.name)

    async def save_resource_group(self, group: ResourceGroup) -> None:
        item = _dump(group)
        item["pk"], item["sk"] = GROUP_PK.format(id=group.id), META
        pointer = {
            **item,
            "pk": WS_GROUPS_PK.format(workspace_id=group.workspace_id),
            "sk": f"GROUP#{group.id}",
        }
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": item}},
                {"Put": {"TableName": self.table, "Item": pointer}},
            ]
        )

    async def delete_resource_group(self, group: ResourceGroup) -> None:
        # Detach members first: DynamoDB has no ON DELETE SET NULL.
        for agent in await self.list_agents(group.workspace_id):
            if agent.resource_group_id == group.id:
                await self._update(
                    AGENT_PK.format(id=agent.id),
                    META,
                    "SET resource_group_id = :null",
                    values={":null": None},
                    condition="attribute_exists(pk)",
                )
        for service in await self.list_services(group.workspace_id):
            if service.resource_group_id == group.id:
                await self._update(
                    SERVICE_PK.format(id=service.id),
                    META,
                    "SET resource_group_id = :null",
                    values={":null": None},
                    condition="attribute_exists(pk)",
                )
        await self._transact(
            [
                {
                    "Delete": {
                        "TableName": self.table,
                        "Key": {"pk": GROUP_PK.format(id=group.id), "sk": META},
                    }
                },
                {
                    "Delete": {
                        "TableName": self.table,
                        "Key": {
                            "pk": WS_GROUPS_PK.format(
                                workspace_id=group.workspace_id
                            ),
                            "sk": f"GROUP#{group.id}",
                        },
                    }
                },
            ]
        )

    # tracing

    async def record_trace_span(self, span: TraceSpan) -> None:
        item = _dump(span)
        key = f"{_iso(span.started_at)}#{span.span_id}"
        primary = {**item, "pk": TRACE_PK.format(trace_id=span.trace_id), "sk": key}
        listing = {
            **item,
            "pk": WS_TRACES_PK.format(workspace_id=span.workspace_id),
            "sk": f"{key}#{span.trace_id}",
        }
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": primary}},
                {"Put": {"TableName": self.table, "Item": listing}},
            ]
        )

    async def list_recent_spans(
        self, workspace_id: uuid.UUID, *, limit: int = 100
    ) -> list[TraceSpan]:
        items = await self._query(
            WS_TRACES_PK.format(workspace_id=workspace_id),
            descending=True,
            limit=limit,
        )
        return [_load(TraceSpan, item) for item in items]

    async def list_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[TraceSpan]:
        items = await self._query(
            WS_TRACES_PK.format(workspace_id=workspace_id),
            sk_before=self._as_of_bound(as_of),
            descending=True,
            limit=limit,
            offset=offset,
            filter_expression="span_id = :root",
            values={":root": "root"},
        )
        return [_load(TraceSpan, item) for item in items]

    async def count_trace_roots(
        self,
        workspace_id: uuid.UUID,
        *,
        as_of: datetime | None = None,
    ) -> int:
        return await self._count(
            WS_TRACES_PK.format(workspace_id=workspace_id),
            sk_before=self._as_of_bound(as_of),
            filter_expression="span_id = :root",
            values={":root": "root"},
        )

    @staticmethod
    def _as_of_bound(as_of: datetime | None) -> str | None:
        if as_of is None:
            return None
        return _iso(as_of + timedelta(microseconds=1))

    async def list_trace_spans(
        self, workspace_id: uuid.UUID, trace_id: str
    ) -> list[TraceSpan]:
        items = await self._query(TRACE_PK.format(trace_id=trace_id))
        spans = [_load(TraceSpan, item) for item in items]
        return [
            span for span in spans if span.workspace_id == workspace_id
        ]

    # bootstrap

    async def get_bootstrap(self) -> BootstrapState | None:
        item = await self._get(BOOTSTRAP_PK)
        return _load(BootstrapState, item) if item else None

    async def mark_bootstrapped(
        self, *, user_id: uuid.UUID, method: str, when: datetime
    ) -> BootstrapState:
        state = BootstrapState(
            id=True,
            completed_at=when,
            completed_by=user_id,
            method=method,
            created_at=utcnow(),
        )
        item = _dump(state)
        item["pk"], item["sk"] = BOOTSTRAP_PK, META
        await self._put(item)
        return state

    # agents

    async def create_agent(
        self,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        kind: str,
        ceiling: dict[str, Any],
        created_by: uuid.UUID | None,
        status: str = "active",
    ) -> Agent:
        agent = Agent(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            kind=kind,
            status=status,
            ceiling=ceiling,
            created_by=created_by,
            created_at=utcnow(),
        )
        item = _dump(agent)
        item["pk"], item["sk"] = AGENT_PK.format(id=agent.id), META
        try:
            await self._transact(
                [
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": AGENT_SLUG_PK.format(
                                    workspace_id=workspace_id, slug=slug
                                ),
                                "sk": META,
                                "target_id": str(agent.id),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": WS_AGENTS_PK.format(workspace_id=workspace_id),
                                "sk": f"{_iso(agent.created_at)}#{agent.id}",
                            },
                        }
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "agent slug already exists") from exc
            raise
        return agent

    async def get_agent(self, agent_id: uuid.UUID) -> Agent | None:
        item = await self._get(AGENT_PK.format(id=agent_id))
        return _load(Agent, item) if item else None

    async def get_agent_by_slug(
        self, workspace_id: uuid.UUID, slug: str
    ) -> Agent | None:
        target = await self._target(
            AGENT_SLUG_PK.format(workspace_id=workspace_id, slug=slug)
        )
        return await self.get_agent(target) if target else None

    async def list_agents(
        self, workspace_id: uuid.UUID, *, only_agent_id: uuid.UUID | None = None
    ) -> list[Agent]:
        links = await self._query(WS_AGENTS_PK.format(workspace_id=workspace_id))
        keys = [
            (AGENT_PK.format(id=uuid.UUID(link["sk"].rsplit("#", 1)[1])), META)
            for link in links
        ]
        agents = [_load(Agent, item) for item in await self._batch_get(keys)]
        if only_agent_id is not None:
            agents = [agent for agent in agents if agent.id == only_agent_id]
        return sorted(agents, key=lambda entry: entry.created_at)

    async def save_agent(self, agent: Agent) -> None:
        item = _dump(agent)
        item["pk"], item["sk"] = AGENT_PK.format(id=agent.id), META
        await self._put(item)

    # credentials

    async def create_credential(
        self,
        *,
        agent_id: uuid.UUID,
        type: str,
        prefix: str | None = None,
        secret_hash: bytes | None = None,
        cert_fingerprint: str | None = None,
        cert_pem: str | None = None,
        serial_number: str | None = None,
        issuer: str | None = None,
        spiffe_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> AgentCredential:
        credential = AgentCredential(
            id=uuid.uuid4(),
            agent_id=agent_id,
            type=type,
            prefix=prefix,
            secret_hash=secret_hash,
            cert_fingerprint=cert_fingerprint,
            cert_pem=cert_pem,
            serial_number=serial_number,
            issuer=issuer,
            spiffe_id=spiffe_id,
            expires_at=expires_at,
            created_at=utcnow(),
        )
        item = _dump(credential)
        item["pk"] = AGENT_PK.format(id=agent_id)
        item["sk"] = f"CREDENTIAL#{credential.id}"
        items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self.table,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        ]
        if prefix:
            items.append(
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": CREDENTIAL_PREFIX_PK.format(prefix=prefix),
                            "sk": META,
                            "target_id": str(agent_id),
                            "credential_id": str(credential.id),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                }
            )
        await self._transact(items)
        return credential

    async def get_credential(
        self, agent_id: uuid.UUID, credential_id: uuid.UUID
    ) -> AgentCredential | None:
        item = await self._get(
            AGENT_PK.format(id=agent_id), f"CREDENTIAL#{credential_id}"
        )
        return _load(AgentCredential, item) if item else None

    async def get_credential_by_prefix(
        self, prefix: str, credential_type: str
    ) -> AgentCredential | None:
        link = await self._link(CREDENTIAL_PREFIX_PK.format(prefix=prefix))
        if not link:
            return None
        credential = await self.get_credential(
            uuid.UUID(link["target_id"]), uuid.UUID(link["credential_id"])
        )
        if credential is None or credential.type != credential_type:
            return None
        return credential

    async def list_active_credentials(
        self, agent_id: uuid.UUID
    ) -> list[AgentCredential]:
        items = await self._query(
            AGENT_PK.format(id=agent_id), sk_prefix="CREDENTIAL#"
        )
        return [
            _load(AgentCredential, item)
            for item in items
            if item.get("revoked_at") is None
        ]

    async def revoke_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None:
        await self._update(
            AGENT_PK.format(id=credential.agent_id),
            f"CREDENTIAL#{credential.id}",
            "SET revoked_at = :when",
            values={":when": _iso(when)},
            condition="attribute_exists(pk)",
        )

    async def touch_credential(
        self, credential: AgentCredential, when: datetime
    ) -> None:
        await self._update(
            AGENT_PK.format(id=credential.agent_id),
            f"CREDENTIAL#{credential.id}",
            "SET last_used_at = :when",
            values={":when": _iso(when)},
            condition="attribute_exists(pk)",
        )

    async def revoke_credentials_for_agent(
        self, agent_id: uuid.UUID, when: datetime
    ) -> None:
        for credential in await self.list_active_credentials(agent_id):
            await self.revoke_credential(credential, when)

    # enrollment tokens

    async def create_enrollment_token(
        self,
        *,
        workspace_id: uuid.UUID,
        agent_slug: str,
        role_id: uuid.UUID,
        ceiling: dict[str, Any],
        prefix: str,
        secret_hash: bytes,
        expires_at: datetime,
        created_by: uuid.UUID,
    ) -> EnrollmentToken:
        token = EnrollmentToken(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            agent_slug=agent_slug,
            role_id=role_id,
            ceiling=ceiling,
            prefix=prefix,
            secret_hash=secret_hash,
            state="active",
            expires_at=expires_at,
            created_by=created_by,
            created_at=utcnow(),
        )
        item = _dump(token)
        item["pk"], item["sk"] = ENROLLMENT_PK.format(id=token.id), META
        await self._transact(
            [
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": item,
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": ENROLLMENT_PREFIX_PK.format(prefix=prefix),
                            "sk": META,
                            "target_id": str(token.id),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ]
        )
        return token

    async def get_enrollment_token(
        self, token_id: uuid.UUID
    ) -> EnrollmentToken | None:
        item = await self._get(ENROLLMENT_PK.format(id=token_id))
        return _load(EnrollmentToken, item) if item else None

    async def find_enrollment_token_by_prefix(
        self, prefix: str
    ) -> EnrollmentToken | None:
        target = await self._target(ENROLLMENT_PREFIX_PK.format(prefix=prefix))
        token = await self.get_enrollment_token(target) if target else None
        if token is None or token.state != "active":
            return None
        return token

    async def consume_enrollment_token(
        self, token: EnrollmentToken, when: datetime
    ) -> bool:
        return await self._update(
            ENROLLMENT_PK.format(id=token.id),
            META,
            "SET #state = :consumed, consumed_at = :when",
            names={"#state": "state"},
            values={":consumed": "consumed", ":when": _iso(when)},
            condition="#state = :active",
            condition_values={":active": "active"},
        )

    async def set_enrollment_token_state(
        self, token: EnrollmentToken, state: str
    ) -> None:
        await self._update(
            ENROLLMENT_PK.format(id=token.id),
            META,
            "SET #state = :state",
            names={"#state": "state"},
            values={":state": state},
        )

    # device flow

    async def create_device_code(
        self,
        *,
        device_code_hash: bytes,
        user_code: str,
        agent_name: str,
        requested_role: str | None,
        expires_at: datetime,
        interval_seconds: int,
    ) -> EnrollmentDeviceCode:
        code = EnrollmentDeviceCode(
            id=uuid.uuid4(),
            device_code_hash=device_code_hash,
            user_code=user_code,
            status="pending",
            agent_name=agent_name,
            requested_role=requested_role,
            attempts=0,
            expires_at=expires_at,
            interval_seconds=interval_seconds,
            created_at=utcnow(),
        )
        item = _dump(code)
        item["pk"], item["sk"] = DEVICE_PK.format(id=code.id), META
        digest = device_code_hash.hex()
        await self._transact(
            [
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": item,
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": DEVICE_USER_CODE_PK.format(user_code=user_code),
                            "sk": META,
                            "target_id": str(code.id),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": DEVICE_HASH_PK.format(digest=digest),
                            "sk": META,
                            "target_id": str(code.id),
                        },
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ]
        )
        return code

    async def get_device_code(
        self, code_id: uuid.UUID
    ) -> EnrollmentDeviceCode | None:
        item = await self._get(DEVICE_PK.format(id=code_id))
        return _load(EnrollmentDeviceCode, item) if item else None

    async def get_device_code_by_user_code(
        self, user_code: str
    ) -> EnrollmentDeviceCode | None:
        target = await self._target(
            DEVICE_USER_CODE_PK.format(user_code=user_code)
        )
        return await self.get_device_code(target) if target else None

    async def get_device_code_by_hash(
        self, device_code_hash: bytes
    ) -> EnrollmentDeviceCode | None:
        target = await self._target(
            DEVICE_HASH_PK.format(digest=device_code_hash.hex())
        )
        return await self.get_device_code(target) if target else None

    async def device_user_code_exists(self, user_code: str) -> bool:
        return (
            await self._link(DEVICE_USER_CODE_PK.format(user_code=user_code))
            is not None
        )

    async def save_device_code(self, code: EnrollmentDeviceCode) -> None:
        item = _dump(code)
        item["pk"], item["sk"] = DEVICE_PK.format(id=code.id), META
        await self._put(item)

    # services

    async def create_service(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        kind: str,
        endpoint: str | None,
        auth_type: str,
        credential_policy: str,
        created_by: uuid.UUID | None,
    ) -> UpstreamService:
        service = UpstreamService(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            name=name,
            kind=kind,
            endpoint=endpoint,
            auth_type=auth_type,
            auth_config={},
            credential_policy=credential_policy,
            runtime_requirements={},
            status="active",
            created_by=created_by,
            created_at=utcnow(),
        )
        item = _dump(service)
        item["pk"], item["sk"] = SERVICE_PK.format(id=service.id), META
        try:
            await self._transact(
                [
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": item,
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": SERVICE_NAME_PK.format(
                                    workspace_id=workspace_id, name=name
                                ),
                                "sk": META,
                                "target_id": str(service.id),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": WS_SERVICES_PK.format(
                                    workspace_id=workspace_id
                                ),
                                "sk": f"{name}#{service.id}",
                            },
                        }
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            if _condition_failed(exc):
                raise ApiError(409, "conflict", "service name already exists") from exc
            raise
        return service

    async def get_service(self, service_id: uuid.UUID) -> UpstreamService | None:
        item = await self._get(SERVICE_PK.format(id=service_id))
        return _load(UpstreamService, item) if item else None

    async def list_services(self, workspace_id: uuid.UUID) -> list[UpstreamService]:
        links = await self._query(WS_SERVICES_PK.format(workspace_id=workspace_id))
        keys = [
            (SERVICE_PK.format(id=uuid.UUID(link["sk"].rsplit("#", 1)[1])), META)
            for link in links
        ]
        services = [_load(UpstreamService, item) for item in await self._batch_get(keys)]
        return sorted(services, key=lambda entry: entry.name)

    async def list_services_by_ids(
        self, service_ids: Sequence[uuid.UUID]
    ) -> list[UpstreamService]:
        keys = [(SERVICE_PK.format(id=service_id), META) for service_id in service_ids]
        return [_load(UpstreamService, item) for item in await self._batch_get(keys)]

    async def save_service(self, service: UpstreamService) -> None:
        item = _dump(service)
        item["pk"], item["sk"] = SERVICE_PK.format(id=service.id), META
        await self._put(item)

    # tools

    async def list_tools(self, service_id: uuid.UUID) -> list[ServiceTool]:
        items = await self._query(
            SERVICE_PK.format(id=service_id), sk_prefix="TOOL#"
        )
        tools = [_load(ServiceTool, item) for item in items]
        return sorted(tools, key=lambda entry: entry.name)

    async def tool_names(self, service_id: uuid.UUID) -> set[str]:
        items = await self._query(
            SERVICE_PK.format(id=service_id),
            sk_prefix="TOOL#",
            projection="sk",
        )
        return {item["sk"].split("#", 1)[1] for item in items}

    async def get_tool(
        self, service_id: uuid.UUID, name: str
    ) -> ServiceTool | None:
        item = await self._get(SERVICE_PK.format(id=service_id), f"TOOL#{name}")
        return _load(ServiceTool, item) if item else None

    async def save_tool(self, tool: ServiceTool) -> None:
        if tool.id is None:
            tool.id = uuid.uuid4()
        if tool.first_seen_at is None:
            tool.first_seen_at = utcnow()
        if tool.last_seen_at is None:
            tool.last_seen_at = tool.first_seen_at
        item = _dump(tool)
        item["pk"] = SERVICE_PK.format(id=tool.service_id)
        item["sk"] = f"TOOL#{tool.name}"
        await self._put(item)

    # grants

    async def get_grant(
        self, agent_id: uuid.UUID, service_id: uuid.UUID
    ) -> AgentGrant | None:
        item = await self._get(
            AGENT_PK.format(id=agent_id), f"GRANT#{service_id}"
        )
        return _load(AgentGrant, item) if item else None

    async def list_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]:
        items = await self._query(
            AGENT_PK.format(id=agent_id), sk_prefix="GRANT#"
        )
        grants = [_load(AgentGrant, item) for item in items]
        return sorted(grants, key=lambda entry: entry.created_at)

    async def list_active_grants(self, agent_id: uuid.UUID) -> list[AgentGrant]:
        return [
            grant for grant in await self.list_grants(agent_id) if grant.status == "active"
        ]

    async def save_grant(self, grant: AgentGrant) -> None:
        if grant.id is None:
            grant.id = uuid.uuid4()
        if grant.created_at is None:
            grant.created_at = utcnow()
        if grant.updated_at is None:
            grant.updated_at = grant.created_at
        item = _dump(grant)
        item["pk"] = AGENT_PK.format(id=grant.agent_id)
        item["sk"] = f"GRANT#{grant.service_id}"
        await self._transact(
            [
                {"Put": {"TableName": self.table, "Item": item}},
                {
                    "Put": {
                        "TableName": self.table,
                        "Item": {
                            "pk": SERVICE_GRANTS_PK.format(
                                service_id=grant.service_id
                            ),
                            "sk": str(grant.agent_id),
                        },
                    }
                },
            ]
        )

    async def revoke_grant(self, grant: AgentGrant) -> None:
        await self._revoke_grant_item(grant)

    async def _revoke_grant_item(self, grant: AgentGrant) -> None:
        await self._transact(
            [
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": {
                            "pk": AGENT_PK.format(id=grant.agent_id),
                            "sk": f"GRANT#{grant.service_id}",
                        },
                        "UpdateExpression": "SET #status = :revoked",
                        "ConditionExpression": "attribute_exists(pk)",
                        "ExpressionAttributeNames": {"#status": "status"},
                        "ExpressionAttributeValues": {":revoked": "revoked"},
                    }
                },
                {
                    "Delete": {
                        "TableName": self.table,
                        "Key": {
                            "pk": SERVICE_GRANTS_PK.format(
                                service_id=grant.service_id
                            ),
                            "sk": str(grant.agent_id),
                        },
                    }
                },
            ]
        )

    async def revoke_grants_for_agent(self, agent_id: uuid.UUID) -> None:
        for grant in await self.list_active_grants(agent_id):
            await self._revoke_grant_item(grant)

    async def revoke_grants_for_service(self, service_id: uuid.UUID) -> None:
        links = await self._query(
            SERVICE_GRANTS_PK.format(service_id=service_id)
        )
        for link in links:
            grant = await self.get_grant(uuid.UUID(link["sk"]), service_id)
            if grant is not None:
                await self._revoke_grant_item(grant)
            else:
                await self._call(
                    self.client.delete_item,
                    TableName=self.table,
                    Key=self._encode_item(
                        {
                            "pk": SERVICE_GRANTS_PK.format(service_id=service_id),
                            "sk": link["sk"],
                        }
                    ),
                )

    # connections

    async def list_connections(
        self, workspace_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[ServiceConnection]:
        links = await self._query(AGENT_CONNECTIONS_PK.format(agent_id=agent_id))
        keys = [
            (CONNECTION_PK.format(id=uuid.UUID(link["sk"])), META)
            for link in links
        ]
        return [
            _load(ServiceConnection, item)
            for item in await self._batch_get(keys)
            if item.get("workspace_id") == str(workspace_id)
        ]

    # catalog

    async def list_catalog(
        self, workspace_id: uuid.UUID, kind: str | None
    ) -> list[tuple[ServiceTool, UpstreamService]]:
        rows: list[tuple[ServiceTool, UpstreamService]] = []
        for service in await self.list_services(workspace_id):
            if service.status != "active":
                continue
            if kind and service.kind != kind:
                continue
            for tool in await self.list_tools(service.id):
                rows.append((tool, service))
                if len(rows) >= 2000:
                    return rows
        rows.sort(key=lambda row: row[0].name)
        return rows

    # audit

    async def record_audit(
        self,
        *,
        workspace_id: uuid.UUID | None,
        actor_type: str,
        actor_id: uuid.UUID | None,
        action: str,
        trace_id: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            reason=reason,
            trace_id=trace_id,
            meta=meta or {},
            created_at=utcnow(),
        )
        item = _dump(event)
        item["pk"] = AUDIT_PK.format(
            workspace_id=str(workspace_id) if workspace_id else "none"
        )
        item["sk"] = f"{_iso(event.created_at)}#{event.id}"
        await self._put(item)
        return event

    def _audit_filter(
        self,
        since: datetime | None,
        decision: str | None,
        as_of: datetime | None,
    ) -> tuple[
        str | None,
        str | None,
        dict[str, str] | None,
        dict[str, Any] | None,
    ]:
        conditions: list[str] = []
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        if decision is not None:
            conditions.append("#decision = :decision")
            names["#decision"] = "decision"
            values[":decision"] = decision
        if as_of is not None:
            conditions.append("created_at <= :as_of")
            values[":as_of"] = _iso(as_of)
        return (
            _iso(since) if since else None,
            " AND ".join(conditions) or None,
            names or None,
            values or None,
        )

    async def list_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        limit: int = 100,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> list[AuditEvent]:
        sk_from, filter_expression, names, values = self._audit_filter(
            since, decision, as_of
        )
        items = await self._query(
            AUDIT_PK.format(workspace_id=workspace_id),
            sk_from=sk_from,
            descending=True,
            limit=limit,
            offset=offset,
            names=names,
            filter_expression=filter_expression,
            values=values,
        )
        return [_load(AuditEvent, item) for item in items]

    async def count_audit(
        self,
        workspace_id: uuid.UUID,
        *,
        since: datetime | None = None,
        decision: str | None = None,
        as_of: datetime | None = None,
    ) -> int:
        sk_from, filter_expression, names, values = self._audit_filter(
            since, decision, as_of
        )
        return await self._count(
            AUDIT_PK.format(workspace_id=workspace_id),
            sk_from=sk_from,
            filter_expression=filter_expression,
            names=names,
            values=values,
        )


class DynamoStoreProvider:
    def __init__(self, settings: Settings) -> None:
        import boto3

        region = (
            settings.dynamodb_region
            or settings.aws_region
            or None
        )
        self.settings = settings
        self.client = boto3.client(
            "dynamodb",
            region_name=region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )
        self._store = DynamoStore(self.client, settings.dynamodb_table)

    async def startup(self, *, create_tables: bool = False) -> None:
        if create_tables:
            await self._create_table()
        await seed_builtin_roles(self._store)

    async def shutdown(self) -> None:
        return None

    @asynccontextmanager
    async def store(self) -> AsyncIterator[Store]:
        yield self._store

    async def _create_table(self) -> None:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(
                self.client.describe_table, TableName=self.settings.dynamodb_table
            )
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceNotFoundException":
                raise
        await asyncio.to_thread(
            self.client.create_table,
            TableName=self.settings.dynamodb_table,
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = self.client.get_waiter("table_exists")
        await asyncio.to_thread(
            waiter.wait, TableName=self.settings.dynamodb_table
        )


__all__ = ["DynamoStore", "DynamoStoreProvider"]
