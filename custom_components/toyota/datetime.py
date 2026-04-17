# pylint: disable=W0212, W0511

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any, Coroutine, Literal, cast
from xmlrpc.client import DateTime

from homeassistant.components.datetime import DateTimeEntityDescription, DateTimeEntity
from homeassistant.helpers.entity import EntityCategory, HomeAssistantError
from .const import DOMAIN
from .entity import ToyotaBaseEntity


if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import StateType
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    from pytoyoda.models.vehicle import Vehicle

    from . import VehicleData

_LOGGER = logging.getLogger(__name__)


class ToyotaDateTimeEntityDescription(DateTimeEntityDescription, frozen_or_thawed=True):
    """Describes a Toyota sensor entity."""

    value_fn: Callable[[Vehicle], datetime | None] | None = None
    attributes_fn: Callable[[Vehicle], dict[str, Any] | None] | None = None
    validate_fn: Callable[[datetime], None] | None = None


def _validate_next_charging_time(value: datetime) -> None:
    """Validierung für next_charging_event_time."""
    if value < datetime.now(tz=value.tzinfo) or value > datetime.now(
        tz=value.tzinfo
    ) + timedelta(days=7):
        raise HomeAssistantError(
            f"Ungültige Zeit: {value}. Zeit muss zwischen jetzt und 7 Tage in der Zukunft liegen."
        )
    if value.minute % 5 != 0:
        raise HomeAssistantError(
            f"Ungültige Zeit: {value}. Die Toyota Api akzeptiert nur 5 Minuten Sprünge."
        )


VIN_ENTITY_DESCRIPTION = ToyotaDateTimeEntityDescription(
    key="next_charging_event_time",
    translation_key="next_charging_event_time",
    icon="mdi:car-clock",
    entity_category=EntityCategory.CONFIG,
    validate_fn=_validate_next_charging_time,
)


def create_sensor_configurations(metric_values: bool) -> list[dict[str, Any]]:  # noqa : FBT001
    """Create a list of sensor configurations based on vehicle capabilities.

    Args:
        metric_values: Whether to use metric units

    Returns:
        List of sensor configurations

    """

    return [
        {
            "description": VIN_ENTITY_DESCRIPTION,
            "capability_check": lambda v: True,  # noqa : ARG005
            "native_unit": None,
            "suggested_unit": None,
        },
    ]


class ToyotaSensor(ToyotaBaseEntity, DateTimeEntity):
    """Representation of a Toyota sensor."""

    vehicle: Vehicle

    def __init__(  # noqa: PLR0913
        self,
        coordinator: DataUpdateCoordinator[list[VehicleData]],
        entry_id: str,
        vehicle_index: int,
        description: ToyotaDateTimeEntityDescription,
        last_coordinator_value: datetime | None = None,
    ) -> None:
        """Initialise the ToyotaSensor class."""
        super().__init__(coordinator, entry_id, vehicle_index, description)
        self.description = description

        # Initialisiere zentralen Storage für User-Werte
        if "user_datetime_values" not in self.coordinator.hass.data[DOMAIN]:
            self.coordinator.hass.data[DOMAIN]["user_datetime_values"] = {}

        # Initialer Wert: None (Nutzer muss Wert setzen)
        self._storage_key = f"{self.vehicle.vin}_{self.description.key}"

    @property
    def _user_values_storage(self) -> dict[str, datetime]:
        """Zentraler Storage für alle User-Werte."""
        return self.coordinator.hass.data[DOMAIN]["user_datetime_values"]

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor - NUR der User-Wert."""
        # Gebe IMMER nur den User-Wert zurück, nie den Coordinator-Wert
        return self._user_values_storage.get(self._storage_key)

    async def async_set_value(self, value: datetime):
        """Reagiere auf die Eingabe des Nutzers."""

        _LOGGER.info(
            "Nutzer hat Datetime gesetzt für %s: %s", self.description.key, value
        )

        # Validierung falls vorhanden
        if self.description.validate_fn:
            self.description.validate_fn(value)

        # Speichere User-Wert zentral
        self._user_values_storage[self._storage_key] = value

        # Schreibe State
        self.async_write_ha_state()

        _LOGGER.debug("User-Wert gespeichert: %s = %s", self._storage_key, value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: DataUpdateCoordinator[list[VehicleData]] = hass.data[DOMAIN][
        entry.entry_id
    ]

    sensors: list[ToyotaSensor] = []
    for index, vehicle_data in enumerate(coordinator.data):
        vehicle = vehicle_data["data"]
        metric_values = vehicle_data["metric_values"]

        sensor_configs = create_sensor_configurations(metric_values)

        sensors.extend(
            ToyotaSensor(
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
