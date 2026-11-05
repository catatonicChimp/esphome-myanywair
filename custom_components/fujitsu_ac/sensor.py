import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import CONF_ID

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

CONFIG_SCHEMA = (
    sensor.sensor_schema(
        FujitsuACSensor,
        unit_of_measurement="°C",
        accuracy_decimals=1,
    )
    .extend(
        {
            cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
            cv.Optional(CONF_TYPE, default="ac_temperature"): cv.one_of(
                *SENSOR_TYPES, lower=True
            ),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await sensor.new_sensor(config)
    await cg.register_component(var, config)
    cg.add(var.set_sensor_type(SENSOR_TYPES[config[CONF_TYPE]]))
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
