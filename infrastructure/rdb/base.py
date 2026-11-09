# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import Column, String, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


SCHEMA = "nexent"


class SimpleTableBase(DeclarativeBase):
    pass


class TableBase(DeclarativeBase):
    create_time = Column(TIMESTAMP(timezone=False),
                         server_default=func.now(), doc="Creation time")
    update_time = Column(TIMESTAMP(timezone=False), server_default=func.now(
    ), onupdate=func.now(), doc="Update time")
    created_by = Column(String(100), doc="Creator")
    updated_by = Column(String(100), doc="Updater")
    delete_flag = Column(String(1), default="N",
                         doc="Whether it is deleted. Optional values: Y/N")
    pass
