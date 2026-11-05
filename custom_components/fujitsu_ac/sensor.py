import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import (
    CONF_ACCURACY_DECIMALS,
    CONF_DEVICE_CLASS,
    CONF_ID,
    CONF_UNIT_OF_MEASUREMENT,
)

from . import CONF_FUJITSU_AC_ID, FujitsuACComponent, fujitsu_ac_ns

CONF_TYPE = "type"

SENSOR_TYPES = {
    "ac_temperature": 0,     # 10:33, converted to degrees Celsius
    "status": 1,             # 10:31, raw value
    "supported_modes": 2,    # 11:01, raw bitmask
}

FujitsuACSensor = fujitsu_ac_ns.class_(
    "FujitsuACSensor", sensor.Sensor, cg.Component
)

_SENSOR_SCHEMA = sensor.sensor_schema(FujitsuACSensor).extend(
    {
        cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
        cv.Optional(CONF_TYPE, default="ac_temperature"): cv.one_of(
            *SENSOR_TYPES, lower=True
        ),
    }
)


def _apply_type_defaults(config):
    """Only the temperature sensor is a real temperature; the rest are raw
    counters and must not be labelled with a unit of measurement."""
    if config[CONF_TYPE] == "ac_temperature":
        config.setdefault(CONF_UNIT_OF_MEASUREMENT, "°C")
        config.setdefault(CONF_DEVICE_CLASS, "temperature")
        config.setdefault(CONF_ACCURACY_DECIMALS, 2)
    else:
        config.pop(CONF_UNIT_OF_MEASUREMENT, None)
        config.pop(CONF_DEVICE_CLASS, None)
        config.setdefault(CONF_ACCURACY_DECIMALS, 0)
    return config


CONFIG_SCHEMA = cv.All(
    _SENSOR_SCHEMA.extend(cv.COMPONENT_SCHEMA),
    _apply_type_defaults,
)


async def to_code(config):
    var = await sensor.new_sensor(config)
    await cg.register_component(var, config)
    cg.add(var.set_sensor_type(SENSOR_TYPES[config[CONF_TYPE]]))
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
