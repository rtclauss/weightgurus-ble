"""Config flow for the Weight Gurus BLE integration."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import ConfigFlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ADDRESS,
    CONF_ATHLETE,
    CONF_BIRTHDAY,
    CONF_HEIGHT_CM,
    CONF_SEX,
    DOMAIN,
)
from .metrics import A6UserProfile

ATHLETE_CHOICES = ("", "yes", "no")
SEX_CHOICES = ("", "male", "female")


def _normalize_address(value: str) -> str:
    return value.strip().upper()


def _athlete_form_value(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ""


def _user_schema(default_address: str, default_name: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ADDRESS, default=default_address): cv.string,
            vol.Optional(CONF_NAME, default=default_name): cv.string,
        }
    )


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_HEIGHT_CM,
                default="" if options.get(CONF_HEIGHT_CM) is None else str(options[CONF_HEIGHT_CM]),
            ): cv.string,
            vol.Optional(CONF_BIRTHDAY, default=options.get(CONF_BIRTHDAY, "")): cv.string,
            vol.Required(CONF_SEX, default=options.get(CONF_SEX, "")): vol.In(SEX_CHOICES),
            vol.Required(
                CONF_ATHLETE,
                default=_athlete_form_value(options.get(CONF_ATHLETE)),
            ): vol.In(ATHLETE_CHOICES),
        }
    )


def _validate_options(user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    options: dict[str, Any] = {}

    height_text = user_input.get(CONF_HEIGHT_CM, "").strip()
    if height_text:
        try:
            height_cm = float(height_text)
            if height_cm <= 0:
                raise ValueError
        except ValueError:
            errors[CONF_HEIGHT_CM] = "invalid_height"
        else:
            options[CONF_HEIGHT_CM] = round(height_cm, 1)

    birthday_text = user_input.get(CONF_BIRTHDAY, "").strip()
    if birthday_text:
        try:
            birthday = date.fromisoformat(birthday_text)
        except ValueError:
            errors[CONF_BIRTHDAY] = "invalid_birthday"
        else:
            if birthday > date.today():
                errors[CONF_BIRTHDAY] = "invalid_birthday"
            else:
                options[CONF_BIRTHDAY] = birthday.isoformat()

    sex = user_input.get(CONF_SEX, "").strip().lower()
    if sex:
        if sex not in {"male", "female"}:
            errors[CONF_SEX] = "invalid_sex"
        else:
            options[CONF_SEX] = sex

    athlete_choice = user_input.get(CONF_ATHLETE, "").strip().lower()
    if athlete_choice:
        if athlete_choice == "yes":
            options[CONF_ATHLETE] = True
        elif athlete_choice == "no":
            options[CONF_ATHLETE] = False
        else:
            errors[CONF_ATHLETE] = "invalid_athlete"

    if not errors:
        try:
            A6UserProfile.from_mapping(options)
        except ValueError as err:
            message = str(err).lower()
            if "birthday" in message:
                errors[CONF_BIRTHDAY] = "invalid_birthday"
            elif "sex" in message:
                errors[CONF_SEX] = "invalid_sex"
            elif "boolean" in message:
                errors[CONF_ATHLETE] = "invalid_athlete"
            else:
                errors["base"] = "invalid_profile"

    return options, errors


class WeightGurusBleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Weight Gurus BLE."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._discovered_address = ""
        self._discovered_name = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return WeightGurusBleOptionsFlow(config_entry)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle bluetooth discovery."""
        address = _normalize_address(discovery_info.address)
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self._discovered_address = address
        self._discovered_name = (discovery_info.name or discovery_info.address or "").strip()
        if self._discovered_name:
            self.context["title_placeholders"] = {"name": self._discovered_name}

        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the manual setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = _normalize_address(user_input[CONF_ADDRESS])
            if not address:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME, "").strip()
                title = name or self._discovered_name or address
                data = {CONF_ADDRESS: address}
                if name:
                    data[CONF_NAME] = name
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                default_address=self._discovered_address,
                default_name=self._discovered_name,
            ),
            errors=errors,
        )


class WeightGurusBleOptionsFlow(OptionsFlow):
    """Handle Weight Gurus BLE options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the profile options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            options, errors = _validate_options(user_input)
            if not errors:
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
            errors=errors,
        )
