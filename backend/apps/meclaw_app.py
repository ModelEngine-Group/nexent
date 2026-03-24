from datetime import datetime, timedelta
import json
import logging
import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka import Consumer
from pydantic import BaseModel


class InstanceBase(BaseModel):
    id: str
    name: str
    author: str
    description: str
    status: Optional[str] = None  # 改为可选字段
    created_at: datetime
    model: List[str]
    skills: List[str]
    plugins: List[str]
    token_usage: int
    report_time: datetime
    chat_url: str
    last_report_time: Optional[datetime] = None  # 添加最后上报时间


class InstanceCard(BaseModel):
    id: str
    name: str
    created_at: datetime
    status: str
    author: str
    description: str


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

KAFKA_BOOTSTRAP_SERVERS = "kafka:9093"
KAFKA_TOPIC = "instance-monitoring"
KAFKA_GROUP_ID = "monitor-panel-consumer"

router = APIRouter(prefix="/meclaw", tags=["meclaw"])
logger = logging.getLogger("meclaw_app")


def kafka_consumer_loop():
    """Background Kafka consumer loop."""
    conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "group.id": KAFKA_GROUP_ID,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    }
    consumer = Consumer(conf)
    consumer.subscribe([KAFKA_TOPIC])

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                logger.error(f"Kafka error: {msg.error()}")
                continue

            try:
                payload = msg.value().decode("utf-8")
                data = json.loads(payload)
                required_fields = {
                    "id",
                    "name",
                    "author",
                    "description",
                    "status",
                    "created_at",
                    "report_time",
                    "model",
                    "skills",
                    "plugins",
                    "token_usage",
                    "chat_url",
                }
                if not required_fields.issubset(data.keys()):
                    logger.warning("Missing fields in message")
                    continue

                data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                data["report_time"] = datetime.fromisoformat(data["report_time"].replace("Z", "+00:00"))
                data["last_report_time"] = datetime.now()  # 设置最后上报时间

                # 如果没有 status 字段，默认设置为 "running"
                if "status" not in data or data["status"] is None:
                    data["status"] = "running"

                instance = InstanceBase(**data)
                instances[instance.id] = instance
                update_overview_cache()
                logger.info(f"Updated instance {instance.id}")
            except Exception as exc:
                logger.error(f"Failed to process Kafka message: {exc}")

    except Exception as exc:
        logger.error(f"Kafka consumer loop stopped unexpectedly: {exc}")
    finally:
        consumer.close()


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


def cleanup_expired_instances() -> None:
    """定期清理过期实例，将超过60秒未上报的实例状态置为 'stopped'。"""
    while True:
        try:
            current_time = datetime.now()
            expired_instances = []

            for instance_id, instance in instances.items():
                if instance.last_report_time:
                    time_diff = current_time - instance.last_report_time
                    if time_diff > timedelta(seconds=60):
                        expired_instances.append(instance_id)

            # 将过期实例状态置为 'stopped'
            for instance_id in expired_instances:
                if instance_id in instances:
                    instances[instance_id].status = "stopped"
                    logger.info(f"Instance {instance_id} marked as stopped due to timeout")

            # 如果有实例状态变更，更新缓存
            if expired_instances:
                update_overview_cache()

            # 每30秒检查一次
            threading.Event().wait(30)

        except Exception as exc:
            logger.error(f"Error in cleanup thread: {exc}")
            threading.Event().wait(30)  # 出错后也等待30秒再试


@router.on_event("startup")
async def startup_event() -> None:
    # Step 1: Ensure the Kafka topic exists
    admin_conf = {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
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
                num_partitions=3,          # 可根据需求调整
                replication_factor=1       # 单机测试通常设为1；生产环境建议 ≥2
            )
            futures = admin_client.create_topics([new_topic], operation_timeout=30)
            for topic, future in futures.items():
                try:
                    future.result()  # 触发异常（如果创建失败）
                    logger.info(f"Topic '{topic}' created successfully.")
                except Exception as e:
                    logger.error(f"Failed to create topic '{topic}': {e}")
        else:
            logger.info(f"Topic '{KAFKA_TOPIC}' already exists.")

    except Exception as e:
        logger.error(f"Error while checking/creating Kafka topic: {e}")

    # Step 2: Start Kafka consumer thread
    thread = threading.Thread(target=kafka_consumer_loop, daemon=True)
    thread.start()
    logger.info("Kafka consumer thread started")

    # Step 3: Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_expired_instances, daemon=True)
    cleanup_thread.start()
    logger.info("Cleanup thread started")


@router.get("/overview", response_model=OverviewResponse)
async def get_overview() -> OverviewResponse:
    return OverviewResponse(**overview_cache)


@router.get("/instances", response_model=List[InstanceCard])
async def list_instances() -> List[InstanceCard]:
    return [
        InstanceCard(
            id=inst.id,
            name=inst.name,
            created_at=inst.created_at,
            status=inst.status,
            author=inst.author,
            description=inst.description,
        )
        for inst in instances.values()
    ]


@router.get("/instances/{instance_id}", response_model=InstanceBase)
async def get_instance_detail(instance_id: str) -> InstanceBase:
    if instance_id not in instances:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instances[instance_id]
