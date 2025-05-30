from typing import Dict, Any, List, Optional
import enum
import logging
from dataclasses import dataclass

logger = logging.getLogger("assistant")
logger.setLevel(logging.DEBUG)

# Data Models
@dataclass
class Car:
    vin: str
    make: str
    model: str
    year: int

class CarDetails(enum.Enum):
    VIN = "vin"
    MAKE = "make"
    MODEL = "model"
    YEAR = "year"

# Database Mock
class DatabaseDriver:
    def get_car_by_vin(self, vin: str) -> Optional[Car]:
        if vin == "ABC123":
            return Car(vin="ABC123", make="Toyota", model="Camry", year=2022)
        return None
    
    def create_car(self, vin: str, make: str, model: str, year: int) -> Car:
        return Car(vin=vin, make=make, model=model, year=year)

DB = DatabaseDriver()

class AssistantFnc:
    def __init__(self):
        self._current_car: Optional[Car] = None

    async def lookup_car_by_license_plate(self, license_plate: str, state: str) -> str:
        # Mock implementation; replace with actual database query
        logger.info(f"Looking up car by license plate: {license_plate}, state: {state}")
        # Example: Assume a mock lookup
        return "Vehicle found: 2020 Honda Accord (VIN: XYZ789)"

    def get_functions(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "lookup_car",
                    "description": "Look up a car by VIN number",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vin": {"type": "string", "description": "Vehicle Identification Number"}
                        },
                        "required": ["vin"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_car_profile",
                    "description": "Create a new car profile",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vin": {"type": "string", "description": "Vehicle Identification Number"},
                            "make": {"type": "string", "description": "Car make"},
                            "model": {"type": "string", "description": "Car model"},
                            "year": {"type": "integer", "description": "Car year"}
                        },
                        "required": ["vin", "make", "model", "year"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "lookup_car_by_license_plate",
                    "description": "Look up a car by license plate and state",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "license_plate": {"type": "string", "description": "License plate number"},
                            "state": {"type": "string", "description": "State of registration"}
                        },
                        "required": ["license_plate", "state"]
                    }
                }
            }
        ]
    
    
    async def lookup_car(self, vin: str) -> str:
        car = DB.get_car_by_vin(vin)
        if not car:
            return "No car found with that VIN"
        self._current_car = car
        return f"Found: {car.year} {car.make} {car.model} (VIN: {car.vin})"
    
    async def create_car_profile(self, vin: str, make: str, model: str, year: int) -> str:
        car = DB.create_car(vin, make, model, year)
        self._current_car = car
        return f"Created profile for {year} {make} {model}"

    def has_car(self) -> bool:
        return self._current_car is not None

    def get_car_info(self) -> str:
        if not self._current_car:
            return "No car profile loaded"
        return f"VIN: {self._current_car.vin}, Make: {self._current_car.make}, Model: {self._current_car.model}, Year: {self._current_car.year}"
    
    