#pragma once

#include "esphome/core/component.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/climate/climate.h"
#include "esphome/components/sensor/sensor.h"
// Only present in the build when the corresponding platform is configured.
#ifdef USE_SELECT
#include "esphome/components/select/select.h"
#endif
#ifdef USE_SWITCH
#include "esphome/components/switch/switch.h"
#endif

#include <cmath>
#include <cstdint>
#include <deque>
#include <string>
#include <vector>

namespace esphome {
namespace fujitsu_ac {

// Wire values recovered from the Sensibo anywAiR firmware (see
// dumps/analysis/fuji-firmware-notes.md in this repo's parent project).
enum FujitsuMode : uint8_t {
  FUJITSU_MODE_AUTO = 0x00,
  FUJITSU_MODE_COOL = 0x01,
  FUJITSU_MODE_DRY = 0x02,
  FUJITSU_MODE_FAN = 0x03,
  FUJITSU_MODE_HEAT = 0x04,
};

enum FujitsuFan : uint8_t {
  FUJITSU_FAN_AUTO = 0x00,
  FUJITSU_FAN_QUIET = 0x02,
  FUJITSU_FAN_LOW = 0x05,
  FUJITSU_FAN_MEDIUM = 0x08,
  FUJITSU_FAN_HIGH = 0x0b,
};

// Unit that the AC reports register 10:33 in (depends on the unit's own
// remote/display setting).
enum FujitsuTemperatureUnit : uint8_t {
  FUJITSU_TEMP_FAHRENHEIT = 0,
  FUJITSU_TEMP_CELSIUS = 1,
};

// What a `sensor` entry on this component reports.
enum FujitsuSensorType : uint8_t {
  FUJITSU_SENSOR_AC_TEMPERATURE = 0,  // 10:33, converted to °C
  FUJITSU_SENSOR_STATUS = 1,          // 10:31, raw
  FUJITSU_SENSOR_SUPPORTED_MODES = 2,  // 11:01, raw
};

#ifdef USE_SELECT
// Vertical/horizontal swing wire values are sequential (index == wire value).
static const std::vector<std::string> FUJITSU_VSWING_OPTIONS = {
    "stopped", "fixedTop", "fixedMiddleTop", "fixedMiddleBottom", "fixedBottom"};
static const std::vector<std::string> FUJITSU_HSWING_OPTIONS = {
    "stopped", "fixedLeft", "fixedCenterLeft", "fixedCenter", "fixedCenterRight", "fixedRight"};
#endif

struct FujitsuACState {
  bool have_state{false};
  bool power{false};
  uint8_t mode{FUJITSU_MODE_AUTO};
  float target_temp{NAN};
  uint8_t fan{FUJITSU_FAN_AUTO};
  uint16_t vswing{0};  // 0xFFFF when the unit does not expose louvre positions
  uint16_t hswing{0};
  bool light{false};
  float ac_temp{NAN};   // 10:33, converted to °C
  uint16_t status{0};   // 10:31
  uint16_t supported{0};  // 11:01
};

class FujitsuACComponent;

class FujitsuACChild {
 public:
  virtual ~FujitsuACChild() = default;
  virtual void on_state(const FujitsuACState &state) = 0;
};

class FujitsuACComponent : public PollingComponent, public uart::UARTDevice {
 public:
  void setup() override;
  void loop() override;
  void update() override;
  void dump_config() override;

  void register_child(FujitsuACChild *child) { this->children_.push_back(child); }

  // Commands (queued, sent sequentially with response waits)
  void write_power(bool on);
  void write_mode(uint8_t mode);
  void write_setpoint(float celsius);
  void write_fan(uint8_t fan);
  void write_vertical_swing(uint8_t value);
  void write_horizontal_swing(uint8_t value);
  void write_light(bool on);
  void send_poll();

  // Unit the AC reports register 10:33 in.
  void set_temperature_unit(uint8_t unit) { this->temp_unit_ = unit; }

  const FujitsuACState &state() const { return this->state_; }

 protected:
  struct Command {
    std::vector<uint8_t> frame;
    bool single{false};
    uint16_t reg_id{0};
    bool poll{false};
  };

  static std::vector<uint8_t> build_frame_(uint8_t type, const std::vector<uint8_t> &payload);
  void queue_frame_(std::vector<uint8_t> frame, bool single, uint16_t reg_id, bool poll);
  void write_register_(uint8_t tag, uint8_t addr, uint16_t value);
  void process_rx_();
  bool apply_entry_(uint8_t tag, uint8_t addr, uint16_t value);
  void handle_frame_(const uint8_t *frame);
  void publish_state_();

  std::vector<FujitsuACChild *> children_;
  std::deque<Command> queue_;
  std::vector<uint8_t> rx_;
  uint32_t rx_bytes_{0};
  FujitsuACState state_;
  uint8_t temp_unit_{FUJITSU_TEMP_FAHRENHEIT};
  bool waiting_{false};
  bool frame_seen_{false};
  bool published_once_{false};
  uint32_t last_tx_{0};
};

class FujitsuClimate : public climate::Climate, public Component, public FujitsuACChild {
 public:
  climate::ClimateTraits traits() override;
  void control(const climate::ClimateCall &call) override;
  void on_state(const FujitsuACState &state) override;
  void set_parent(FujitsuACComponent *parent) { this->parent_ = parent; }

 protected:
  FujitsuACComponent *parent_{nullptr};
  bool power_{false};
};

#ifdef USE_SELECT
class FujitsuSwingSelect : public select::Select, public Component, public FujitsuACChild {
 public:
  void control(size_t index) override;
  void on_state(const FujitsuACState &state) override;
  void set_parent(FujitsuACComponent *parent) { this->parent_ = parent; }
  void set_vertical(bool vertical) { this->vertical_ = vertical; }

 protected:
  FujitsuACComponent *parent_{nullptr};
  bool vertical_{true};
};
#endif  // USE_SELECT

#ifdef USE_SWITCH
class FujitsuLightSwitch : public switch_::Switch, public Component, public FujitsuACChild {
 public:
  void write_state(bool state) override;
  void on_state(const FujitsuACState &state) override { this->publish_state(state.light); }
  void set_parent(FujitsuACComponent *parent) { this->parent_ = parent; }

 protected:
  FujitsuACComponent *parent_{nullptr};
};
#endif  // USE_SWITCH

class FujitsuACSensor : public sensor::Sensor, public Component, public FujitsuACChild {
 public:
  void on_state(const FujitsuACState &state) override;
  void set_sensor_type(uint8_t type) { this->sensor_type_ = type; }
  void set_parent(FujitsuACComponent *parent) { (void) parent; }

 protected:
  uint8_t sensor_type_{FUJITSU_SENSOR_AC_TEMPERATURE};
};

}  // namespace fujitsu_ac
}  // namespace esphome
