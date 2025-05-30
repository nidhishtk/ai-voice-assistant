import sqlite3
from typing import Optional
from dataclasses import dataclass
from contextlib import contextmanager

@dataclass
class Car:
    vin: str
    make: str
    model: str
    year: int

class DatabaseDriver:
    def __init__(self, db_path: str ="auto_db.sqlite"):
        self.db_path = db_path
        self.__init__db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def __init__db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS cars (
                           vin TEXT PRIMARY KEY,
                           make TEXT NOT NULL,
                           model TEXT NOT NULL,
                           year INTEGER NOT NULL
                           )
                           """)
            conn.commit()

    def get_car_by_vin(self, vin: str) -> Optional[Car]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cars WHERE vin =?", (vin,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return Car(
                vin=row[0],
                make=row[1],
                model=row[2],
                year=row[3]
            )
