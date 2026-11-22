"""Add-device form, reconfigure form and the sensitivity options."""
from __future__ import annotations

import logging
from typing import Any

import av

try:  # Home Assistant 2026.6+ replaced voluptuous with probatio
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONFIRM_FRAMES,
    CONF_HOLD_SECONDS,
    CONF_IGNORE_AREAS,
    CONF_MIN_PERCENT,
    CONF_PATH,
    CONF_PIXEL_THRESHOLD,
    DEFAULT_CONFIRM_FRAMES,
    DEFAULT_HOLD_SECONDS,
    DEFAULT_IGNORE_AREAS,
    DEFAULT_MIN_PERCENT,
    DEFAULT_PATH,
    DEFAULT_PIXEL_THRESHOLD,
    DEFAULT_PORT,
    DOMAIN,
)
from .hub import build_url, parse_areas

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
PORT_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(min=1, max=65535, mode=selector.NumberSelectorMode.BOX)
)


class CannotConnect(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


def probe_stream(url: str) -> tuple[int, int]:
    """Open the stream and decode one frame. Runs in the executor."""
    try:
        with av.open(
            url,
            options={"rtsp_transport": "tcp", "timeout": "5000000"},
            timeout=(10, 5),
        ) as container:
            stream = container.streams.video[0]
            for frame in container.decode(stream):
                return frame.width, frame.height
    except av.error.HTTPUnauthorizedError as err:
        raise CannotConnect("invalid_auth") from err
    except av.error.HTTPNotFoundError as err:
        raise CannotConnect("stream_not_found") from err
    except (av.error.FFmpegError, OSError, IndexError) as err:
        _LOGGER.debug("Probe failed: %s", err)
        raise CannotConnect("cannot_connect") from err
    raise CannotConnect("cannot_connect")


def _connection_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Camera"))] = str
    fields.update(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): PORT_SELECTOR,
            vol.Required(CONF_PATH, default=defaults.get(CONF_PATH, DEFAULT_PATH)): str,
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): PASSWORD_SELECTOR,
        }
    )
    return vol.Schema(fields)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data.pop(CONF_NAME, None)
    data[CONF_HOST] = data[CONF_HOST].strip()
    data[CONF_PORT] = int(data[CONF_PORT])
    data[CONF_PATH] = data[CONF_PATH].strip().lstrip("/")
    return data


class RtspMotionConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> str | None:
        try:
            await self.hass.async_add_executor_job(probe_stream, build_url(data))
        except CannotConnect as err:
            return err.error
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}/{data[CONF_PATH]}")
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(data)) is None:
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema({}, with_name=True), user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}/{data[CONF_PATH]}")
            self._abort_if_unique_id_mismatch(reason="different_camera")
            if (error := await self._async_validate(data)) is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data), with_name=False),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RtspMotionOptionsFlow()


class RtspMotionOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_areas(user_input.get(CONF_IGNORE_AREAS, ""))
            except ValueError:
                errors[CONF_IGNORE_AREAS] = "invalid_areas"
            else:
                user_input.setdefault(CONF_IGNORE_AREAS, "")
                return self.async_create_entry(data=user_input)

        o = user_input or self.config_entry.options

        def num(minimum, maximum, step, unit=None):
            config = selector.NumberSelectorConfig(
                min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
            )
            if unit:
                config["unit_of_measurement"] = unit
            return selector.NumberSelector(config)

        schema = vol.Schema(
            {
                vol.Required(CONF_MIN_PERCENT, default=o.get(CONF_MIN_PERCENT, DEFAULT_MIN_PERCENT)):
                    num(0.01, 100, 0.01, "%"),
                vol.Required(CONF_PIXEL_THRESHOLD, default=o.get(CONF_PIXEL_THRESHOLD, DEFAULT_PIXEL_THRESHOLD)):
                    num(1, 255, 1),
                vol.Required(CONF_CONFIRM_FRAMES, default=o.get(CONF_CONFIRM_FRAMES, DEFAULT_CONFIRM_FRAMES)):
                    num(0, 30, 1),
                vol.Required(CONF_HOLD_SECONDS, default=o.get(CONF_HOLD_SECONDS, DEFAULT_HOLD_SECONDS)):
                    num(1, 600, 1, "s"),
                # suggested_value instead of default, so the field can be emptied (no ignored area).
                vol.Optional(
                    CONF_IGNORE_AREAS,
                    description={"suggested_value": o.get(CONF_IGNORE_AREAS, DEFAULT_IGNORE_AREAS)},
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
