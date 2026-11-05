import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import climate

from . import CONF_FUJITSU_AC_ID, FujitsuACComponent, fujitsu_ac_ns

FujitsuClimate = fujitsu_ac_ns.class_(
    "FujitsuClimate", climate.Climate, cg.Component
)

CONFIG_SCHEMA = (
    climate.climate_schema(FujitsuClimate)
    .extend(
        {
            cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await climate.new_climate(config)
    await cg.register_component(var, config)
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
    cg.add(var.set_parent(parent))
