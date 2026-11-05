import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import uart
from esphome.const import CONF_ID, CONF_UART_ID

CODEOWNERS = ["@ataylor"]
DEPENDENCIES = ["uart"]

CONF_FUJITSU_AC_ID = "fujitsu_ac_id"

fujitsu_ac_ns = cg.esphome_ns.namespace("fujitsu_ac")
FujitsuACComponent = fujitsu_ac_ns.class_(
    "FujitsuACComponent", cg.PollingComponent, uart.UARTDevice
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(FujitsuACComponent),
            cv.Required(CONF_UART_ID): cv.use_id(uart.UARTComponent),
        }
    )
    .extend(cv.polling_component_schema("5s"))
    .extend(uart.UART_DEVICE_SCHEMA)
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await uart.register_uart_device(var, config)
