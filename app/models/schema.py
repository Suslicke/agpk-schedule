from sqlalchemy import Column, String, Integer
from sqlalchemy.sql.sqltypes import DateTime
from sqlalchemy.ext.declarative import declarative_base
import json

Base = declarative_base()

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    group = Column(String)
    week_start = Column(DateTime)
    week_type = Column(String)
    timetable = Column(String)

class GroupLoad(Base):
    __tablename__ = "group_loads"
    id = Column(Integer, primary_key=True)
    group = Column(String)
    load = Column(String)

    def to_dict(self):
        return {
            "id": self.id,
            "group": self.group,
            "load": json.loads(self.load)
        }