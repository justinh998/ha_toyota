from functools import partial
from typing import TYPE_CHECKING, Any, Awaitable, Callable, cast
from . import VehicleData
from .entity import ToyotaBaseEntity
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from pytoyoda.models.vehicle import Vehicle
from collections.abc import Coroutine
from pytoyoda.models.endpoints.common import StatusModel
from homeassistant.components.sensor import ConfigEntry, HomeAssistant
from homeassistant.helpers.entity import HomeAssistantError
from .const import DOMAIN
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .utils import run_pytoyoda_sync,get_vehicle_capability
from pytoyoda.models.endpoints.electric import (
    NextChargeSettings,
    ReservationCharge,
    ChargeTime,
)
import calendar
import homeassistant.util.dt as dt_util

class ToyotaButtonEntityDescription(ButtonEntityDescription, frozen_or_thawed=True):
    press_action: Callable[[Vehicle], Awaitable[StatusModel]] | None = None
    charge_type: str | None = None
    # Beispiel-Buttons für ein Fahrzeug


async def refresh_battery(vehicle: Vehicle) -> None:
    await vehicle.refresh_electric_realtime_status()  # StatusModel wird ignoriert


REFRESH_ELECTRIC_ENTITY_DESCRIPTION = ToyotaButtonEntityDescription(
    key="refresh_electric",
    translation_key="refresh_electric",
    icon="mdi:flash",
    press_action=lambda vehicle: vehicle.refresh_electric_realtime_status(),
)
CHARGE_NOW_ENTITY_DESCRIPTION = ToyotaButtonEntityDescription(
    key="charge_now",
    translation_key="charge_now",
    icon="mdi:ev-station",
    press_action=lambda vehicle: vehicle.send_next_charging_command(
        NextChargeSettings(command="CHARGE_NOW")
    ),
)
SET_START_CHARGING_TIME_ENTITY_DESCRIPTION = ToyotaButtonEntityDescription(
    key="set_start_charging_time",
    translation_key="set_start_charging_time",
    icon="mdi:timer-play-outline",
    charge_type="SET_CHARGING_START_TIME",
)
SET_END_CHARGING_TIME_ENTITY_DESCRIPTION = ToyotaButtonEntityDescription(
    key="set_end_charging_time",
    translation_key="set_end_charging_time",
    icon="mdi:timer-stop-outline",
    charge_type="SET_CHARGING_END_TIME",
)


def create_sensor_configurations() -> list[dict[str, Any]]:  # noqa : FBT001
    """Create a list of sensor configurations based on vehicle capabilities.

    Args:
        vehicle: The vehicle object
        metric_values: Whether to use metric units

    Returns:
        List of sensor configurations

    """

    return [
        {
            "description": REFRESH_ELECTRIC_ENTITY_DESCRIPTION,
            "capability_check": lambda v: get_vehicle_capability(
                v, "econnect_vehicle_status_capable"
            )
            or v.type == "electric",
        },
        {
            "description": CHARGE_NOW_ENTITY_DESCRIPTION,
            "capability_check": lambda v: get_vehicle_capability(
                v, "econnect_vehicle_status_capable"
            )
            or v.type == "electric",
        },
        {
            "description": SET_START_CHARGING_TIME_ENTITY_DESCRIPTION,
            "capability_check": lambda v: get_vehicle_capability(
                v, "econnect_vehicle_status_capable"
            )
            or v.type == "electric",
        },
        {
            "description": SET_END_CHARGING_TIME_ENTITY_DESCRIPTION,
            "capability_check": lambda v: get_vehicle_capability(
                v, "econnect_vehicle_status_capable"
            )
            or v.type == "electric",
        },
    ]


# Button-Entity-Klasse
class ToyotaButtonEntity(ToyotaBaseEntity, ButtonEntity):
    vehicle: Vehicle
    entity_description: ToyotaButtonEntityDescription

    def __init__(  # noqa: PLR0913
        self,
        coordinator: DataUpdateCoordinator[list[VehicleData]],
        entry_id: str,
        vehicle_index: int,
        description: ToyotaButtonEntityDescription,
    ) -> None:
        """Initialise the ToyotaButton class."""
        super().__init__(coordinator, entry_id, vehicle_index, description)
        self.description = description

    async def async_press(self) -> None:
        if self.description.press_action:
            coro = self.description.press_action(self.vehicle)
        elif self.description.charge_type == "SET_CHARGING_START_TIME":
            if (
                f"{self.vehicle.vin}_next_charging_event_time"
                in self.hass.data[DOMAIN]["user_datetime_values"]
            ):
                CurrentNextChargingEventUserTime = self.hass.data[DOMAIN][
                    "user_datetime_values"
                ][f"{self.vehicle.vin}_next_charging_event_time"].astimezone(
                    dt_util.get_time_zone(self.hass.config.time_zone)
                )
            else:
                raise HomeAssistantError(
                    "Es wurde kein Start/Ende Ladezeitpunkt gesetzt."
                )
            coro = self.vehicle.send_next_charging_command(
                NextChargeSettings(
                    command="RESERVE_CHARGE",
                    reservationCharge=ReservationCharge(
                        chargeType="SET_CHARGING_START_TIME",
                        day=calendar.day_name[
                            CurrentNextChargingEventUserTime.weekday()
                        ].upper(),
                        startTime=ChargeTime(
                            hour=CurrentNextChargingEventUserTime.hour,
                            minute=CurrentNextChargingEventUserTime.minute,
                        ),
                    ),
                )
            )
        elif self.description.charge_type == "SET_CHARGING_END_TIME":
            if (
                f"{self.vehicle.vin}_next_charging_event_time"
                in self.hass.data[DOMAIN]["user_datetime_values"]
            ):
                CurrentNextChargingEventUserTime = self.hass.data[DOMAIN][
                    "user_datetime_values"
                ][f"{self.vehicle.vin}_next_charging_event_time"].astimezone(
                    dt_util.get_time_zone(self.hass.config.time_zone)
                )
            else:
                raise HomeAssistantError(
                    "Es wurde kein Start/Ende Ladezeitpunkt gesetzt."
                )
            coro = self.vehicle.send_next_charging_command(
                NextChargeSettings(
                    command="RESERVE_CHARGE",
                    reservationCharge=ReservationCharge(
                        chargeType="SET_CHARGING_END_TIME",
                        day=calendar.day_name[
                            CurrentNextChargingEventUserTime.weekday()
                        ].upper(),
                        endTime=ChargeTime(
                            hour=CurrentNextChargingEventUserTime.hour,
                            minute=CurrentNextChargingEventUserTime.minute,
                        ),
                    ),
                )
            )
        else:
            raise HomeAssistantError(f"No press_action defined for {self.entity_id}")
        await self.hass.async_add_executor_job(
            run_pytoyoda_sync, cast(Coroutine, coro)
        )

    async def async_press_set_start_charging(self) -> None:
        coro = self.vehicle.send_next_charging_command(
            NextChargeSettings(
                command="RESERVE_CHARGE",
                reservationCharge=ReservationCharge(
                    chargeType="SET_CHARGING_START_TIME",
                    day=self.hass.data[DOMAIN]["CurrentNextChargingEventUserTime"].day,
                    startTime=ChargeTime(
                        hour=self.hass.data[DOMAIN][
                            "CurrentNextChargingEventUserTime"
                        ].hour,
                        minute=self.hass.data[DOMAIN][
                            "CurrentNextChargingEventUserTime"
                        ].minute,
                    ),
                ),
            )
        )
        await self.hass.async_add_executor_job(
            run_pytoyoda_sync, cast(Coroutine, coro)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: DataUpdateCoordinator[list[VehicleData]] = hass.data[DOMAIN][
        entry.entry_id
    ]

    sensors: list[ToyotaButtonEntity] = []
    for index, vehicle_data in enumerate(coordinator.data):
        vehicle = vehicle_data["data"]

        sensor_configs = create_sensor_configurations()

        sensors.extend(
            ToyotaButtonEntity(
                coordinator=coordinator,
                entry_id=entry.entry_id,
                vehicle_index=index,
                description=config["description"],
            )
            for config in sensor_configs
            if not config["description"].key.startswith("current_")
            and config["capability_check"](vehicle)
        )
    async_add_devices(sensors)
