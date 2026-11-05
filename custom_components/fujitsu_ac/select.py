import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import select

from . import CONF_FUJITSU_AC_ID, FujitsuACComponent, fujitsu_ac_ns

CONF_SWING = "swing"

FujitsuSwingSelect = fujitsu_ac_ns.class_(
    "FujitsuSwingSelect", select.Select, cg.Component
)

VSWING_OPTIONS = ["stopped", "fixedTop", "fixedMiddleTop", "fixedMiddleBottom", "fixedBottom"]
HSWING_OPTIONS = ["stopped", "fixedLeft", "fixedCenterLeft", "fixedCenter", "fixedCenterRight", "fixedRight"]

SWINGS = {
    "vertical": VSWING_OPTIONS,
    "horizontal": HSWING_OPTIONS,
}

CONFIG_SCHEMA = (
    select.select_schema(FujitsuSwingSelect)
    .extend(
        {
            cv.GenerateID(CONF_FUJITSU_AC_ID): cv.use_id(FujitsuACComponent),
            cv.Required(CONF_SWING): cv.one_of(*SWINGS, lower=True),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    options = SWINGS[config[CONF_SWING]]
    var = await select.new_select(config, options=options)
    await cg.register_component(var, config)
    cg.add(var.set_vertical(config[CONF_SWING] == "vertical"))
    parent = await cg.get_variable(config[CONF_FUJITSU_AC_ID])
    cg.add(parent.register_child(var))
    cg.add(var.set_parent(parent))
