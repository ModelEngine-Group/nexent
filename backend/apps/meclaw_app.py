from datetime import datetime, timedelta
from http import HTTPStatus
import json
import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka import Consumer
from pydantic import BaseModel

from consts.const import CAN_EDIT_ALL_USER_ROLES, IS_SPEED_MODE, MECLAW_KAFKA_BOOTSTRAP_SERVERS
from consts.exceptions import UnauthorizedError
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.auth_utils import get_current_user_id

# Author field sometimes carries creator user id (UUID) from producers; used when
# created_by_user_id is omitted.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class InstanceBase(BaseModel):
    id: str
    name: str
    author: str
    description: str
    status: Optional[str] = None
    created_at: datetime
    model: List[str]
    skills: List[str]
    plugins: List[str]
    token_usage: int
    report_time: datetime
    chat_url: str
    tenant_id: Optional[str] = None
    created_by_user_id: Optional[str] = None


class InstanceCard(BaseModel):
    id: str
    name: str
    created_at: datetime
    status: str
    author: str
    description: str
    chat_url: str
    tenant_id: Optional[str] = None
    created_by_user_id: Optional[str] = None


class OverviewResponse(BaseModel):
    running_count: int
    total_count: int
    total_token_usage: int


instances: Dict[str, InstanceBase] = {}
overview_cache = {
    "running_count": 0,
    "total_count": 0,
    "total_token_usage": 0,
}

# FastAPI may invoke APIRouter startup handlers more than once during application
# startup (e.g. instrumentation or router merge). Guard so Kafka threads/history
# load run only once.
_meclaw_kafka_startup_lock = threading.Lock()
_meclaw_kafka_startup_done = False

# Cache: creator user_id -> (user_email, tenant_id) from user_tenant_t
_creator_profile_lock = threading.Lock()
_CREATOR_PROFILE_CACHE: Dict[str, tuple[Optional[str], Optional[str]]] = {}

KAFKA_TOPIC = "instance-monitoring"
KAFKA_GROUP_ID = "monitor-panel-consumer"

router = APIRouter(prefix="/meclaw", tags=["meclaw"])
logger = logging.getLogger("meclaw_app")


def _parse_meclaw_timestamp(value: str) -> datetime:
    """Parse ISO 8601 and normalize to system local timezone (not UTC)."""
    s = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone()


def _normalize_instance_payload(data: dict) -> None:
    """Coerce optional legacy string payloads for skills/plugins to List[str].

    ``model`` must be List[str] in messages; string ``model`` is no longer accepted.
    """
    for key in ("skills", "plugins"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif isinstance(val, str):
            data[key] = [val]
        elif isinstance(val, list):
            data[key] = [str(x) for x in val]
        else:
            data[key] = [str(val)]


def _apply_meclaw_identity_fields(data: dict) -> None:
    """Normalize tenant_id and creator id for access control.

    Typical Kafka payload includes ``id``, ``name``, ``created_by_user_id``,
    ``description``, ``status``, ``created_at``, ``model``, ``skills``, ``plugins``,
    ``token_usage``, ``report_time``, ``chat_url`` — without ``author`` or
    ``tenant_id``. Those are filled from ``user_tenant_t`` when serving APIs.
    If ``author`` is omitted, a placeholder is set so ``InstanceBase`` can parse
    (display email comes from DB). Legacy: ``author`` as UUID fills
    ``created_by_user_id``.
    """
    tid = data.get("tenant_id")
    if tid is not None and str(tid).strip():
        data["tenant_id"] = str(tid).strip()
    else:
        data["tenant_id"] = None

    cid = data.get("created_by_user_id") or data.get("created_by")
    if cid is not None and str(cid).strip():
        data["created_by_user_id"] = str(cid).strip()
    else:
        auth = data.get("author")
        if isinstance(auth, str) and _UUID_RE.match(auth.strip()):
            data["created_by_user_id"] = auth.strip()
        else:
            data["created_by_user_id"] = None

    if not data.get("author"):
        data["author"] = str(data.get("created_by_user_id") or "")


def _get_creator_profile(user_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return (user_email, tenant_id) for a platform user id; results are cached."""
    if not user_id:
        return None, None
    with _creator_profile_lock:
        if user_id in _CREATOR_PROFILE_CACHE:
            return _CREATOR_PROFILE_CACHE[user_id]
    try:
        record = get_user_tenant_by_user_id(user_id)
    except Exception as exc:
        logger.warning("Meclaw: user_tenant lookup failed for %s: %s", user_id, exc)
        with _creator_profile_lock:
            _CREATOR_PROFILE_CACHE[user_id] = (None, None)
        return None, None
    if not record:
        with _creator_profile_lock:
            _CREATOR_PROFILE_CACHE[user_id] = (None, None)
        return None, None
    email = (record.get("user_email") or "").strip() or None
    tid = (record.get("tenant_id") or "").strip() or None
    with _creator_profile_lock:
        _CREATOR_PROFILE_CACHE[user_id] = (email, tid)
    return email, tid


def _effective_tenant_id(inst: InstanceBase) -> str:
    """Tenant for ACL: prefer DB row for creator when ``created_by_user_id`` is set."""
    uid = _instance_creator_user_id(inst)
    if uid:
        _, tid = _get_creator_profile(uid)
        if tid:
            return tid.strip()
    raw = (inst.tenant_id or "").strip() if inst.tenant_id else ""
    return raw


def _enrich_instance_for_api(inst: InstanceBase) -> InstanceBase:
    """Set ``author`` to user email and ``tenant_id`` from DB when creator is known."""
    uid = _instance_creator_user_id(inst)
    if not uid:
        return inst
    email, tid = _get_creator_profile(uid)
    updates: Dict[str, str] = {}
    if email:
        updates["author"] = email
    if tid:
        updates["tenant_id"] = tid
    if not updates:
        return inst
    return inst.model_copy(update=updates)


def _instance_creator_user_id(inst: InstanceBase) -> str:
    if inst.created_by_user_id:
        return str(inst.created_by_user_id).strip()
    if isinstance(inst.author, str) and _UUID_RE.match(inst.author.strip()):
        return inst.author.strip()
    return ""


def _meclaw_auth_context(authorization: Optional[str]) -> tuple[str, str, str]:
    """Return (user_id, tenant_id, user_role_upper). Raises HTTPException on auth failure."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    record = get_user_tenant_by_user_id(user_id) or {}
    user_role = str(record.get("user_role") or "").upper()
    return user_id, tenant_id, user_role


def visible_meclaw_instances(user_id: str, tenant_id: str, user_role: str) -> List[InstanceBase]:
    """Instances visible to the caller (same pattern as agent list: admin sees tenant-wide)."""
    role_upper = str(user_role or "").upper()
    can_see_all_in_tenant = role_upper in CAN_EDIT_ALL_USER_ROLES

    if IS_SPEED_MODE:
        return list(instances.values())

    visible: List[InstanceBase] = []
    for inst in instances.values():
        it = _effective_tenant_id(inst)
        if not it or it != tenant_id:
            continue
        if can_see_all_in_tenant:
            visible.append(inst)
            continue
        creator = _instance_creator_user_id(inst)
        if creator and creator == user_id:
            visible.append(inst)
    return visible


def _can_access_instance(
    inst: InstanceBase,
    user_id: str,
    tenant_id: str,
    user_role: str,
) -> bool:
    if IS_SPEED_MODE:
        return True
    role_upper = str(user_role or "").upper()
    can_see_all_in_tenant = role_upper in CAN_EDIT_ALL_USER_ROLES
    it = _effective_tenant_id(inst)
    if not it or it != tenant_id:
        return False
    if can_see_all_in_tenant:
        return True
    creator = _instance_creator_user_id(inst)
    return bool(creator) and creator == user_id


def _overview_from_instances(inst_list: List[InstanceBase]) -> OverviewResponse:
    total = len(inst_list)
    running = sum(1 for i in inst_list if i.status == "running")
    total_tokens = sum(i.token_usage for i in inst_list)
    return OverviewResponse(
        running_count=running,
        total_count=total,
        total_token_usage=total_tokens,
    )


def kafka_consumer_loop():
    """Background Kafka consumer loop."""
    while True:
        conf = {
            "bootstrap.servers": MECLAW_KAFKA_BOOTSTRAP_SERVERS,
            "group.id": KAFKA_GROUP_ID,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }

        consumer = None
        try:
            consumer = Consumer(conf)
            consumer.subscribe([KAFKA_TOPIC])
        except Exception as exc:
            logger.error(f"Failed to create Kafka consumer: {exc}")
            time.sleep(5)
            continue

        try:
            while True:
                try:
                    msg = consumer.poll(timeout=1.0)
                    if msg is None:
                        continue
                    if msg.error():
                        logger.error(f"Kafka error: {msg.error()}")
                        continue

                    try:
                        payload = msg.value().decode("utf-8")
                        data = json.loads(payload)
                        if "status" not in data or data["status"] is None:
                            data["status"] = "running"
                        data["created_at"] = _parse_meclaw_timestamp(data["created_at"])
                        data["report_time"] = _parse_meclaw_timestamp(data["report_time"])
                        _normalize_instance_payload(data)
                        _apply_meclaw_identity_fields(data)

                        instance = InstanceBase(**data)
                        instances[instance.id] = instance
                        update_overview_cache()
                        logger.info(f"Updated instance {instance.id}")
                    except Exception as exc:
                        logger.error(f"Failed to process Kafka message: {exc}")
                except Exception as exc:
                    logger.error(f"Error in kafka consumer cycle: {exc}")

        except Exception as exc:
            logger.error(f"Kafka consumer loop stopped unexpectedly: {exc}")
        finally:
            if consumer is not None:
                try:
                    consumer.close()
                except Exception as exc:
                    logger.error(f"Failed to close Kafka consumer: {exc}")

        time.sleep(5)


def update_overview_cache() -> None:
    total = len(instances)
    running = sum(1 for inst in instances.values() if inst.status == "running")
    total_tokens = sum(inst.token_usage for inst in instances.values())
    overview_cache.update(
        {
            "running_count": running,
            "total_count": total,
            "total_token_usage": total_tokens,
        }
    )


def load_historical_instances_from_kafka(max_wait_time: int = 60) -> int:
    """Load instance snapshots from Kafka on startup (read from earliest).

    Uses a unique consumer group per process start so each restart replays the
    log from the beginning instead of resuming a stored group offset.
    """
    conf_history = {
        "bootstrap.servers": MECLAW_KAFKA_BOOTSTRAP_SERVERS,
        # Unique group: ensures auto.offset.reset=earliest applies every cold start
        "group.id": f"{KAFKA_GROUP_ID}-history-{uuid.uuid4().hex}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }

    instances_by_key: Dict[str, InstanceBase] = {}
    start_time = datetime.now()

    try:
        consumer_history = Consumer(conf_history)
        consumer_history.subscribe([KAFKA_TOPIC])
    except Exception as exc:
        logger.error(f"Failed to create Kafka history consumer: {exc}")
        return 0

    try:
        while (datetime.now() - start_time).total_seconds() < max_wait_time:
            msg = consumer_history.poll(timeout=1.0)
            if msg is None:
                # Keep polling until max_wait_time: assignment and first fetch
                # can take several seconds; the old 5s break caused empty loads.
                continue

            if msg.error():
                logger.error(f"Kafka error during history pull: {msg.error()}")
                continue

            try:
                payload = msg.value().decode("utf-8")
                data = json.loads(payload)
                if "status" not in data or data["status"] is None:
                    data["status"] = "running"
                data["created_at"] = _parse_meclaw_timestamp(data["created_at"])
                data["report_time"] = _parse_meclaw_timestamp(data["report_time"])
                _normalize_instance_payload(data)
                _apply_meclaw_identity_fields(data)
                # Kafka key as unique identifier; fallback to instance id
                key = None
                if msg.key() is not None:
                    try:
                        key = msg.key().decode("utf-8")
                    except Exception:
                        key = None
                if not key:
                    key = data.get("id")

                if not key:
                    logger.warning("Historical message without key/id, skipped")
                    continue

                instance = InstanceBase(**data)
                instances_by_key[key] = instance
            except Exception as exc:
                logger.error(f"Failed to process historical Kafka message: {exc}")

    except Exception as e:
        logger.error(f"Error pulling historical data from Kafka: {e}")
    finally:
        consumer_history.close()

    now = datetime.now().astimezone()
    for inst in instances_by_key.values():
        if inst.report_time and (now - inst.report_time) > timedelta(seconds=120):
            inst.status = "stopped"

    for inst in instances_by_key.values():
        instances[inst.id] = inst

    update_overview_cache()

    return len(instances_by_key)


def cleanup_expired_instances() -> None:
    """Mark instances as stopped when last report is older than 120 seconds."""
    while True:
        try:
            current_time = datetime.now().astimezone()
            expired_instances = []

            for instance_id, instance in instances.items():
                if instance.report_time:
                    time_diff = current_time - instance.report_time
                    if time_diff > timedelta(seconds=120) and instance.status != "stopped":
                        expired_instances.append(instance_id)

            for instance_id in expired_instances:
                if instance_id in instances and instances[instance_id].status != "stopped":
                    instances[instance_id].status = "stopped"
                    logger.info(f"Instance {instance_id} marked as stopped due to timeout")

            if expired_instances:
                update_overview_cache()

            threading.Event().wait(30)

        except Exception as exc:
            logger.error(f"Error in cleanup thread: {exc}")
            threading.Event().wait(30)


@router.on_event("startup")
async def startup_event() -> None:
    global _meclaw_kafka_startup_done
    with _meclaw_kafka_startup_lock:
        if _meclaw_kafka_startup_done:
            logger.info(
                "Meclaw Kafka startup skipped (already initialized; duplicate "
                "startup invocation suppressed)."
            )
            return
        _meclaw_kafka_startup_done = True

    try:
        # Step 1: Ensure the Kafka topic exists
        admin_conf = {
            "bootstrap.servers": MECLAW_KAFKA_BOOTSTRAP_SERVERS,
        }
        admin_client = AdminClient(admin_conf)

        try:
            # List existing topics
            metadata = admin_client.list_topics(timeout=10)
            existing_topics = metadata.topics.keys()

            if KAFKA_TOPIC not in existing_topics:
                logger.info(f"Topic '{KAFKA_TOPIC}' not found. Creating it...")
                new_topic = NewTopic(
                    topic=KAFKA_TOPIC,
                    num_partitions=3,
                    replication_factor=1,
                    config={"cleanup.policy": "compact", "min.compaction.lag.ms": "0", "min.cleanable.dirty.ratio": "0.1"}
                )
                futures = admin_client.create_topics([new_topic], operation_timeout=30)
                for topic, future in futures.items():
                    try:
                        future.result()
                        logger.info(f"Topic '{topic}' created successfully.")
                    except Exception as e:
                        logger.error(f"Failed to create topic '{topic}': {e}")
            else:
                logger.info(f"Topic '{KAFKA_TOPIC}' already exists.")

        except Exception as e:
            logger.error(f"Error while checking/creating Kafka topic: {e}")

        # Step 2: Pull historical data from Kafka on startup
        logger.info("Pulling historical data from Kafka topic...")
        loaded_count = load_historical_instances_from_kafka(max_wait_time=30)
        logger.info(f"Historical data pull completed. Loaded {loaded_count} unique instance keys.")

        # Step 3: Start Kafka consumer thread
        thread = threading.Thread(target=kafka_consumer_loop, daemon=True)
        thread.start()
        logger.info("Kafka consumer thread started")

        # Step 4: Start cleanup thread
        cleanup_thread = threading.Thread(target=cleanup_expired_instances, daemon=True)
        cleanup_thread.start()
        logger.info("Cleanup thread started")

    except Exception as exc:
        logger.error(f"startup_event encountered an unexpected error: {exc}")
        with _meclaw_kafka_startup_lock:
            _meclaw_kafka_startup_done = False


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(authorization: Optional[str] = Header(None)) -> OverviewResponse:
    user_id, tenant_id, user_role = _meclaw_auth_context(authorization)
    visible = visible_meclaw_instances(user_id, tenant_id, user_role)
    return _overview_from_instances(visible)


@router.get("/instances", response_model=List[InstanceCard])
async def list_instances(authorization: Optional[str] = Header(None)) -> List[InstanceCard]:
    user_id, tenant_id, user_role = _meclaw_auth_context(authorization)
    visible = visible_meclaw_instances(user_id, tenant_id, user_role)
    cards: List[InstanceCard] = []
    for inst in visible:
        out = _enrich_instance_for_api(inst)
        cards.append(
            InstanceCard(
                id=out.id,
                name=out.name,
                created_at=out.created_at,
                status=out.status or "running",
                author=out.author,
                description=out.description,
                chat_url=out.chat_url,
                tenant_id=out.tenant_id,
                created_by_user_id=out.created_by_user_id,
            )
        )
    return cards


@router.get("/instances/{instance_id}", response_model=InstanceBase)
async def get_instance_detail(
    instance_id: str,
    authorization: Optional[str] = Header(None),
) -> InstanceBase:
    user_id, tenant_id, user_role = _meclaw_auth_context(authorization)
    if instance_id not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")
    inst = instances[instance_id]
    if not _can_access_instance(inst, user_id, tenant_id, user_role):
        raise HTTPException(status_code=404, detail="Instance not found")
    return _enrich_instance_for_api(inst)
