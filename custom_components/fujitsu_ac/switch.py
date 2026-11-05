import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import switch

from . import CONF_FUJITSU_AC_ID, FujitsuACComponent, fujitsu_ac_ns

FujitsuLightSwitch = fujitsu_ac_ns.class_(
    "FujitsuLightSwitch", switch.Switch, cg.Component
)

CONFIG_SCHEMA = switch.switch_schema(FujitsuLightSwitch).extend(
    {
        cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
    }
)


async def to_code(config):
    var = await switch.new_switch(config)
    await cg.register_component(var, config)
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
    cg.add(var.set_parent(parent))
