import json
import uuid
from datetime import datetime, timezone
import glob
import os
import socket
import yaml
from confluent_kafka import Producer

CONFIG_PATH = "/root/.openclaw/openclaw.json"
KAFKA_TOPIC = "instance-monitoring"
KAFKA_CONFIG_PATH = "/opt/nexent/config/agent_config.yaml"

INSTANCE_ID_FILE = os.path.join(os.path.dirname(__file__), "instance_id.txt")


def get_instance_id():
    if os.path.exists(INSTANCE_ID_FILE):
        with open(INSTANCE_ID_FILE, 'r') as f:
            return f.read().strip()
    else:
        new_id = str(uuid.uuid4())
        with open(INSTANCE_ID_FILE, 'w') as f:
            f.write(new_id)
        return new_id


def get_file_creation_time(file_path):
    """获取文件的创建时间，如果不存在或出错，返回默认时间"""
    if not os.path.exists(file_path):
        return "1970-01-01T00:00:00Z"
    try:
        stat = os.stat(file_path)
        # 优先使用 st_birthtime（创建时间），否则使用 st_mtime（修改时间）
        if hasattr(stat, 'st_birthtime'):
            creation_time = stat.st_birthtime
        else:
            creation_time = stat.st_mtime
        dt = datetime.fromtimestamp(creation_time, timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return "1970-01-01T00:00:00Z"


def load_kafka_config():
    """从 YAML 文件读取 Kafka 配置。不存在或解析失败时返回 None。"""
    if not os.path.exists(KAFKA_CONFIG_PATH):
        print(f"Kafka config file not found: {KAFKA_CONFIG_PATH}")
        return None

    if yaml is None:
        print("PyYAML not installed, cannot parse Kafka config")
        return None

    try:
        with open(KAFKA_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
            if isinstance(cfg, dict) and 'kafka' in cfg and isinstance(cfg['kafka'], dict):
                return cfg['kafka']
            else:
                print(f"Kafka config missing 'kafka' section in {KAFKA_CONFIG_PATH}")
                return None
    except Exception as e:
        print(f"Failed to load Kafka config: {e}")
        return None


# 待修改
AUTHOR = ""
DESCRIPTION = ""
STATUS = "running"


def load_agent_config():
    """从 agent_config.yaml 读取全量配置，优先返回 dict"""
    if not os.path.exists(KAFKA_CONFIG_PATH):
        print(f"Agent config file not found: {KAFKA_CONFIG_PATH}")
        return {}

    if yaml is None:
        print("PyYAML not installed, cannot parse agent config")
        return {}

    try:
        with open(KAFKA_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
            if isinstance(cfg, dict):
                return cfg
            print(f"Agent config ({KAFKA_CONFIG_PATH}) is not a dict")
            return {}
    except Exception as e:
        print(f"Failed to load agent config: {e}")
        return {}


def get_created_by_user_id():
    """从 agent_config.yaml 获取 user_id，失败时返回空字符串"""
    cfg = load_agent_config()
    return cfg.get('user_id') or AUTHOR


def extract_token_usage(config):
    """遍历 /root/.openclaw/agents/*/sessions/sessions.json 统计所有 totalTokens"""
    total = 0
    paths = glob.glob("/root/.openclaw/agents/*/sessions/sessions.json")
    for p in paths:
        try:
            print(f"🔍 读取 token usage 文件: {p}")
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 如果是字典，按 key 遍历所有项，取 totalTokens
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, dict) and 'totalTokens' in value:
                        print(f"1Found totalTokens: {value['totalTokens']} in {p}")
                        total += int(value.get('totalTokens', 0) or 0)
                    # 兼容嵌套 sessions 列表结构
                    if isinstance(value, dict) and 'sessions' in value and isinstance(value['sessions'], list):
                        for sess in value['sessions']:
                            if isinstance(sess, dict):
                                print(f"2Found totalTokens in nested session: {sess.get('totalTokens', 0)} in {p}")
                                total += int(sess.get('totalTokens', 0) or 0)

            # 如果是列表，直接遍历每个 session 对象
            elif isinstance(data, list):
                for sess in data:
                    if isinstance(sess, dict):
                        print(f"3Found totalTokens in session list: {sess.get('totalTokens', 0)} in {p}")
                        total += int(sess.get('totalTokens', 0) or 0)

        except Exception:
            continue

    return total


def load_openclaw_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_model(config):
    """从 config 中提取所有 models 的 name"""
    names = []
    try:
        providers = config.get("models", {}).get("providers", {})
        for provider_key, provider_value in providers.items():
            models = provider_value.get("models", [])
            for model in models:
                if isinstance(model, dict) and "name" in model:
                    names.append(model["name"])
    except Exception:
        pass
    return names


def extract_skills(config):
    """从 config 中提取所有技能 key"""
    try:
        entries = config.get("skills", {}).get("entries", {})
        return list(entries.keys()) if entries else []
    except Exception:
        return []


def extract_plugins(config):
    """从 config 中提取所有启用的插件 key"""
    try:
        entries = config.get("plugins", {}).get("entries", {})
        plugins = []
        for name, info in entries.items():
            if isinstance(info, dict) and info.get("enabled", True):  # 默认启用
                plugins.append(name)
        return plugins
    except Exception:
        return []


def extract_chat_url(config):
    """从 /opt/nexent/config/agent_config.yaml 读取 ip，并用默认端口 18789 拼接 URL。"""
    default_ip = "localhost"
    default_port = 18789

    agent_cfg = load_agent_config()
    ip = agent_cfg.get("ip") or default_ip
    ip = str(ip).strip() or default_ip

    url = f"http://{ip}:{default_port}"

    # 兼容传 token 逻辑
    token = None
    if isinstance(agent_cfg, dict):
        token = agent_cfg.get("token") or agent_cfg.get("gateway", {}).get("auth", {}).get("token")
    if not token and isinstance(config, dict):
        token = config.get("gateway", {}).get("auth", {}).get("token")

    if token:
        return f"{url}/#token={token}"

    return url


def build_report_message(config):
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    report = {
        "id": get_instance_id(),
        "name": socket.gethostname(),
        "created_by_user_id": get_created_by_user_id(),
        "description": DESCRIPTION,
        "status": STATUS,
        "created_at": get_file_creation_time(KAFKA_CONFIG_PATH),
        "model": extract_model(config),
        "skills": extract_skills(config),
        "plugins": extract_plugins(config),
        "token_usage": extract_token_usage(config),
        "report_time": now,
        "chat_url": extract_chat_url(config)
    }
    return report


def kafka_producer():
    kafka_cfg = load_kafka_config()
    if not kafka_cfg:
        print("Kafka config not available, skipping Kafka producer")
        return None

    options = {
        'bootstrap.servers': kafka_cfg.get('bootstrap_servers'),
        'security.protocol': kafka_cfg.get('security_protocol', 'SASL_PLAINTEXT'),
        'sasl.mechanisms': kafka_cfg.get('sasl_mechanism', 'PLAIN'),
    }

    if kafka_cfg.get('sasl_username'):
        options['sasl.username'] = kafka_cfg['sasl_username']
    if kafka_cfg.get('sasl_password'):
        options['sasl.password'] = kafka_cfg['sasl_password']

    if not options.get('bootstrap.servers'):
        print("Kafka bootstrap.servers is missing in config, skipping Kafka producer")
        return None

    try:
        return Producer(options)
    except Exception as e:
        print(f"Failed to create Kafka producer: {e}")
        return None


def delivery_report(err, msg):
    if err:
        print(f"Kafka delivery failed: {err}")
    else:
        print(f"Message delivered to {msg.topic()}[{msg.partition()}]")


def main():
    try:
        config = load_openclaw_config()
        report = build_report_message(config)
        print(f"Reporting payload: {report}")
        print(json.dumps(report, indent=2, ensure_ascii=False))

        producer = kafka_producer()
        if producer is None:
            print("Kafka producer unavailable, skipping send")
        else:
            try:
                producer.produce(
                    topic=KAFKA_TOPIC,
                    key=report["id"].encode('utf-8'),
                    value=json.dumps(report, ensure_ascii=False),
                    callback=delivery_report
                )
                remaining = producer.flush(timeout=10)
                if remaining == 0:
                    print("Report sent to Kafka.")
                else:
                    print(f"Kafka send failed: {remaining} messages not delivered")
            except Exception as e:
                print(f"Kafka send failed (ignored): {e}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()