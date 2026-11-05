import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor

from . import CONF_FUJITSU_AC_ID, FujitsuACComponent, fujitsu_ac_ns

FujitsuACTempSensor = fujitsu_ac_ns.class_(
    "FujitsuACTempSensor", sensor.Sensor, cg.Component
)

CONFIG_SCHEMA = (
    sensor.sensor_schema(FujitsuACTempSensor)
    .extend(
        {
            cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await sensor.new_sensor(config)
    await cg.register_component(var, config)
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
