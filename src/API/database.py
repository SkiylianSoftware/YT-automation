"""Database management wrapper functions."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from pathlib import Path
from typing import Type


class Database:
    """Generic database handler."""

    def __init__(self, db_path: Path) -> None:
        """Initialise the database class."""
        self.db_path = f"sqlite:///{db_path.resolve()}"
        self.engine = create_engine(self.db_path)
        self.session = sessionmaker(bind=self.engine)

    def init_db(self, model) -> None:
        """Create a model table if it doesn't already exist."""
        model.metadata.create_all(self.engine)
    
    def upsert(self, model, data: dict[str, str]) -> None:
        """Create or update a record."""
        session = self.session()
        # update
        if instance:= session.query(model).filter_by(id=data["id"]).one_or_none():
            for k,v in data.items():
                setattr(instance, k, v)
        # create
        else:
            instance = model(**data)
            session.add(instance)
        session.commit()
        session.close()
