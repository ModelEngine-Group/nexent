# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy.orm import class_mapper


def as_dict(obj):
    from datetime import datetime

    # Handle SQLAlchemy ORM objects (both TableBase and other DeclarativeBase subclasses)
    if hasattr(obj, "__class__") and hasattr(obj.__class__, "__mapper__"):
        result = {}
        for c in class_mapper(obj.__class__).columns:
            value = getattr(obj, c.key)
            # Convert datetime to ISO format string for JSON serialization
            # Naive datetime (TIMESTAMP WITHOUT TIME ZONE) is treated as local time.
            # Append 'Z' so browsers interpret it as UTC-equivalent local time
            # without shifting.
            if isinstance(value, datetime):
                iso = value.isoformat()
                result[c.key] = iso if value.tzinfo else iso + "Z"
            else:
                result[c.key] = value
        return result

    # noinspection PyProtectedMember
    return dict(obj._mapping)


def filter_property(data, model_class):
    """
    Filter the data dictionary to only include keys that correspond to columns in the model class.

    :param data: Dictionary containing the data to be filtered.
    :param model_class: The SQLAlchemy model class to filter against.
    :return: A new dictionary with only the keys that match the model's columns.
    """
    model_fields = model_class.__table__.columns.keys()
    return {key: value for key, value in data.items() if key in model_fields}
