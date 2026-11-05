#include "fujitsu_ac.h"

namespace esphome {
namespace fujitsu_ac {

static const char *const TAG = "fujitsu_ac";

// Register list from the stock firmware's poll table (its 0x5206 message id
// is sent as the first list entry, followed by tag/addr pairs).
static const uint16_t FUJITSU_POLL_LIST[] = {
    0x5206, 0x1000, 0x1001, 0x1002, 0x1003, 0x1010, 0x1011,
    0x1022, 0x1023, 0x1033, 0x10b6, 0x1101, 0x1031,
};

std::vector<uint8_t> FujitsuACComponent::build_frame_(uint8_t type, const std::vector<uint8_t> &payload) {
  std::vector<uint8_t> frame;
  frame.reserve(payload.size() + 7);
  frame.push_back(type);
  frame.push_back(0x00);
  frame.push_back(0x00);
  frame.push_back(0x00);
  frame.push_back((uint8_t) payload.size());
  frame.insert(frame.end(), payload.begin(), payload.end());
  uint16_t sum = 0;
  for (uint8_t b : frame)
    sum = (uint16_t) (sum + b);
  uint16_t csum = (uint16_t) (0xFFFF - sum);
  frame.push_back((uint8_t) (csum >> 8));
  frame.push_back((uint8_t) (csum & 0xFF));
  return frame;
}

void FujitsuACComponent::queue_frame_(std::vector<uint8_t> frame, bool single, uint16_t reg_id, bool poll) {
  // Coalesce rapid UI changes (e.g. temperature slider) into one pending write.
  if (single) {
    for (auto &cmd : this->queue_) {
      if (cmd.single && cmd.reg_id == reg_id) {
        cmd.frame = std::move(frame);
        return;
      }
    }
  }
  // Never let polls pile up while the queue is backed up.
  if (poll) {
    for (auto &cmd : this->queue_) {
      if (cmd.poll)
        return;
    }
  }
  this->queue_.push_back({std::move(frame), single, reg_id, poll});
  while (this->queue_.size() > 16)
    this->queue_.pop_front();
}

void FujitsuACComponent::write_register_(uint8_t tag, uint8_t addr, uint16_t value) {
  std::vector<uint8_t> payload = {tag, addr, (uint8_t) (value >> 8), (uint8_t) (value & 0xFF)};
  this->queue_frame_(this->build_frame_(0x02, payload), true, (uint16_t) ((tag << 8) | addr), false);
}

void FujitsuACComponent::send_poll() {
  std::vector<uint8_t> payload;
  payload.reserve(sizeof(FUJITSU_POLL_LIST));
  for (uint16_t reg : FUJITSU_POLL_LIST) {
    payload.push_back((uint8_t) (reg >> 8));
    payload.push_back((uint8_t) (reg & 0xFF));
  }
  this->queue_frame_(this->build_frame_(0x03, payload), false, 0, true);
}

void FujitsuACComponent::write_power(bool on) { this->write_register_(0x10, 0x00, on ? 0x0001 : 0x0000); }
void FujitsuACComponent::write_mode(uint8_t mode) { this->write_register_(0x10, 0x01, mode); }

void FujitsuACComponent::write_setpoint(float celsius) {
  float clamped = std::min(30.0f, std::max(16.0f, celsius));
  this->write_register_(0x10, 0x02, (uint16_t) (clamped * 10.0f + 0.5f));
}

void FujitsuACComponent::write_fan(uint8_t fan) { this->write_register_(0x10, 0x03, fan); }

void FujitsuACComponent::write_vertical_swing(uint8_t value) {
  // The stock firmware always pairs 10:10 with a zeroed 10:11 marker.
  std::vector<uint8_t> payload = {
      0x10, 0x10, (uint8_t) (value >> 8), (uint8_t) (value & 0xFF),
      0x10, 0x11, 0x00, 0x00,
  };
  this->queue_frame_(this->build_frame_(0x02, payload), false, 0x1010, false);
}

void FujitsuACComponent::write_horizontal_swing(uint8_t value) {
  std::vector<uint8_t> payload = {
      0x10, 0x22, (uint8_t) (value >> 8), (uint8_t) (value & 0xFF),
      0x10, 0x23, 0x00, 0x00,
  };
  this->queue_frame_(this->build_frame_(0x02, payload), false, 0x1022, false);
}

void FujitsuACComponent::write_light(bool on) { this->write_register_(0x10, 0xb6, on ? 0x0001 : 0x0000); }

void FujitsuACComponent::setup() {
  // Nothing to configure; the UART component is set up before this one.
}

void FujitsuACComponent::update() { this->send_poll(); }

void FujitsuACComponent::loop() {
  // Drain the UART into the frame buffer.
  while (this->available()) {
    uint8_t b;
    if (!this->read_byte(&b))
      break;
    this->rx_bytes_++;
    this->rx_.push_back(b);
    if (this->rx_.size() > 1024)
      this->rx_.clear();  // runaway guard; resync via checksum anyway
  }
  this->process_rx_();

  const uint32_t now = millis();
  if (this->waiting_) {
    if (this->frame_seen_) {
      this->frame_seen_ = false;
      this->waiting_ = false;
      this->queue_.pop_front();
    } else if ((now - this->last_tx_) > 600) {
      const uint8_t cmd_type = this->queue_.front().frame[0];
      if (this->rx_bytes_ == 0) {
        ESP_LOGD(TAG, "No response to command 0x%02X (timeout)", cmd_type);
      } else {
        ESP_LOGW(TAG, "Received %u byte(s) but no valid frame - check UART polarity/baud/wiring (command 0x%02X)",
                 this->rx_bytes_, cmd_type);
      }
      this->rx_bytes_ = 0;
      this->waiting_ = false;
      this->queue_.pop_front();
    }
  } else if (!this->queue_.empty()) {
    this->write_array(this->queue_.front().frame);
    this->last_tx_ = now;
    this->waiting_ = true;
    this->frame_seen_ = false;
  }
}

void FujitsuACComponent::process_rx_() {
  while (this->rx_.size() >= 7) {
    if (this->rx_[0] != 0x02 && this->rx_[0] != 0x03) {
      this->rx_.erase(this->rx_.begin());
      continue;
    }
    const uint8_t payload_len = this->rx_[4];
    const size_t total = (size_t) payload_len + 7;
    if (this->rx_.size() < total)
      return;  // wait for the rest of the frame
    uint16_t sum = 0;
    for (size_t i = 0; i < total - 2; i++)
      sum = (uint16_t) (sum + this->rx_[i]);
    const uint16_t csum = ((uint16_t) this->rx_[total - 2] << 8) | this->rx_[total - 1];
    if ((uint16_t) (sum + csum) != 0xFFFF) {
      this->rx_.erase(this->rx_.begin());
      continue;  // resync by one byte
    }
    ESP_LOGD(TAG, "RX frame: type=0x%02X payload_len=%u", this->rx_[0], payload_len);
    this->rx_bytes_ = 0;
    this->handle_frame_(this->rx_.data());
    this->rx_.erase(this->rx_.begin(), this->rx_.begin() + total);
    this->frame_seen_ = true;
  }
}

bool FujitsuACComponent::apply_entry_(uint8_t tag, uint8_t addr, uint16_t value) {
  FujitsuACState &s = this->state_;
  if (tag == 0x11) {
    if (addr == 0x01 && s.supported != value) {
      s.supported = value;
      return true;
    }
    return false;
  }
  if (tag != 0x10)
    return false;
  switch (addr) {
    case 0x00: {
      const bool p = (value == 0x0001);
      if (s.power != p) {
        s.power = p;
        return true;
      }
      return false;
    }
    case 0x01:
      if (s.mode != (uint8_t) value) {
        s.mode = (uint8_t) value;
        return true;
      }
      return false;
    case 0x02: {
      const float t = (value == 0xFFFF) ? NAN : (value / 10.0f);
      if (t != s.target_temp) {
        s.target_temp = t;
        return true;
      }
      return false;
    }
    case 0x03:
      if (s.fan != (uint8_t) value) {
        s.fan = (uint8_t) value;
        return true;
      }
      return false;
    case 0x10:
      if (s.vswing != value) {
        s.vswing = value;
        return true;
      }
      return false;
    case 0x22:
      if (s.hswing != value) {
        s.hswing = value;
        return true;
      }
      return false;
    case 0x31:
      if (s.status != value) {
        s.status = value;
        return true;
      }
      return false;
    case 0x33: {
      // Firmware treats 0..3 as status codes and 0xFFFF as invalid. The
      // remaining value is the room temperature in the AC's own unit, /100.
      float t = NAN;
      if (value != 0xFFFF && value > 3) {
        const float raw = value / 100.0f;
        t = (this->temp_unit_ == FUJITSU_TEMP_CELSIUS) ? raw : (raw - 32.0f) * 5.0f / 9.0f;
      }
      if (t != s.ac_temp) {
        s.ac_temp = t;
        return true;
      }
      return false;
    }
    case 0xb6: {
      const bool l = (value == 0x0001);
      if (s.light != l) {
        s.light = l;
        return true;
      }
      return false;
    }
    default:
      return false;
  }
}

void FujitsuACComponent::handle_frame_(const uint8_t *frame) {
  const uint8_t type = frame[0];
  const uint8_t payload_len = frame[4];
  if (type != 0x03)
    return;  // write ACK/NACK; the next poll refreshes state
  if (payload_len < 1)
    return;
  const uint8_t marker = frame[5];
  if (marker == 0x02) {
    ESP_LOGW(TAG, "Air conditioner rejected the last command (NACK)");
    return;
  }
  if (marker != 0x01) {
    ESP_LOGW(TAG, "Unknown response marker 0x%02X", marker);
    return;
  }
  // Entries start after the 0x01 marker; the first pseudo-entry is the
  // 0x5206 message id (52 06 ff ff), which the dispatch simply ignores.
  const size_t count = (payload_len - 1) / 4;
  const uint8_t *p = frame + 6;
  bool changed = false;
  for (size_t i = 0; i < count; i++, p += 4)
    changed |= this->apply_entry_(p[0], p[1], ((uint16_t) p[2] << 8) | p[3]);
  this->state_.have_state = true;
  if (changed || !this->published_once_) {
    this->published_once_ = true;
    // Integer formatting only: %f is unavailable in the default ESPHome printf.
    ESP_LOGD(TAG, "State: power=%d mode=0x%02X target=%d.%dC fan=0x%02X vswing=0x%04X hswing=0x%04X light=%d ac_temp=%d.%02d",
             this->state_.power, this->state_.mode, (int) this->state_.target_temp,
             (int) (this->state_.target_temp * 10) % 10, this->state_.fan, this->state_.vswing,
             this->state_.hswing, this->state_.light, (int) this->state_.ac_temp,
             (int) (this->state_.ac_temp * 100) % 100);
    this->publish_state_();
  }
}

void FujitsuACComponent::publish_state_() {
  for (auto *child : this->children_)
    child->on_state(this->state_);
}

void FujitsuACComponent::dump_config() {
  ESP_LOGCONFIG(TAG, "Fujitsu anywAiR AC:");
  ESP_LOGCONFIG(TAG, "  Protocol: Sensibo/Fujitsu UART 9600 8N1 (fw e91f184)");
}

// ---------------------------------------------------------------------------
// Climate
// ---------------------------------------------------------------------------

static uint8_t mode_wire_from_climate(climate::ClimateMode m) {
  switch (m) {
    case climate::CLIMATE_MODE_COOL:
      return FUJITSU_MODE_COOL;
    case climate::CLIMATE_MODE_DRY:
      return FUJITSU_MODE_DRY;
    case climate::CLIMATE_MODE_FAN_ONLY:
      return FUJITSU_MODE_FAN;
    case climate::CLIMATE_MODE_HEAT:
      return FUJITSU_MODE_HEAT;
    default:
      return FUJITSU_MODE_AUTO;  // CLIMATE_MODE_HEAT_COOL
  }
}

static climate::ClimateMode mode_from_wire(uint8_t w) {
  switch (w) {
    case FUJITSU_MODE_COOL:
      return climate::CLIMATE_MODE_COOL;
    case FUJITSU_MODE_DRY:
      return climate::CLIMATE_MODE_DRY;
    case FUJITSU_MODE_FAN:
      return climate::CLIMATE_MODE_FAN_ONLY;
    case FUJITSU_MODE_HEAT:
      return climate::CLIMATE_MODE_HEAT;
    default:
      return climate::CLIMATE_MODE_HEAT_COOL;
  }
}

static uint8_t fan_wire_from_climate(climate::ClimateFanMode f) {
  switch (f) {
    case climate::CLIMATE_FAN_QUIET:
      return FUJITSU_FAN_QUIET;
    case climate::CLIMATE_FAN_LOW:
      return FUJITSU_FAN_LOW;
    case climate::CLIMATE_FAN_MEDIUM:
      return FUJITSU_FAN_MEDIUM;
    case climate::CLIMATE_FAN_HIGH:
      return FUJITSU_FAN_HIGH;
    default:
      return FUJITSU_FAN_AUTO;
  }
}

static climate::ClimateFanMode fan_from_wire(uint8_t w) {
  switch (w) {
    case FUJITSU_FAN_QUIET:
      return climate::CLIMATE_FAN_QUIET;
    case FUJITSU_FAN_LOW:
      return climate::CLIMATE_FAN_LOW;
    case FUJITSU_FAN_MEDIUM:
      return climate::CLIMATE_FAN_MEDIUM;
    case FUJITSU_FAN_HIGH:
      return climate::CLIMATE_FAN_HIGH;
    default:
      return climate::CLIMATE_FAN_AUTO;
  }
}

climate::ClimateTraits FujitsuClimate::traits() {
  auto traits = climate::ClimateTraits();
  // The AC's own room temperature (10:33) is fed to current_temperature, in °C.
  traits.add_feature_flags(climate::CLIMATE_SUPPORTS_CURRENT_TEMPERATURE);
  traits.set_supported_modes({climate::CLIMATE_MODE_OFF, climate::CLIMATE_MODE_HEAT_COOL,
                              climate::CLIMATE_MODE_COOL, climate::CLIMATE_MODE_DRY,
                              climate::CLIMATE_MODE_FAN_ONLY, climate::CLIMATE_MODE_HEAT});
  traits.set_supported_fan_modes({climate::CLIMATE_FAN_AUTO, climate::CLIMATE_FAN_QUIET,
                                  climate::CLIMATE_FAN_LOW, climate::CLIMATE_FAN_MEDIUM,
                                  climate::CLIMATE_FAN_HIGH});
  traits.set_visual_min_temperature(16);
  traits.set_visual_max_temperature(30);
  traits.set_visual_temperature_step(0.5);
  return traits;
}

void FujitsuClimate::control(const climate::ClimateCall &call) {
  const auto mode = call.get_mode();
  if (mode.has_value()) {
    if (*mode == climate::CLIMATE_MODE_OFF) {
      this->parent_->write_power(false);
      this->power_ = false;
    } else {
      // The stock firmware sends power and mode as separate register writes.
      if (!this->power_) {
        this->parent_->write_power(true);
        this->power_ = true;
      }
      this->parent_->write_mode(mode_wire_from_climate(*mode));
    }
    this->mode = *mode;
  }
  const auto target = call.get_target_temperature();
  if (target.has_value()) {
    this->parent_->write_setpoint(*target);
    this->target_temperature = *target;
  }
  const auto fan = call.get_fan_mode();
  if (fan.has_value()) {
    this->parent_->write_fan(fan_wire_from_climate(*fan));
    this->fan_mode = *fan;
  }
  this->publish_state();
}

void FujitsuClimate::on_state(const FujitsuACState &s) {
  this->power_ = s.power;
  this->mode = s.power ? mode_from_wire(s.mode) : climate::CLIMATE_MODE_OFF;
  if (!std::isnan(s.target_temp))
    this->target_temperature = s.target_temp;
  if (!std::isnan(s.ac_temp))
    this->current_temperature = s.ac_temp;
  this->fan_mode = fan_from_wire(s.fan);
  this->publish_state();
}

// ---------------------------------------------------------------------------
// Swing selects
// ---------------------------------------------------------------------------

#ifdef USE_SELECT
void FujitsuSwingSelect::control(size_t index) {
  // Wire values are sequential, so the option index IS the register value.
  if (this->vertical_)
    this->parent_->write_vertical_swing((uint8_t) index);
  else
    this->parent_->write_horizontal_swing((uint8_t) index);
  this->publish_state(index);
}

void FujitsuSwingSelect::on_state(const FujitsuACState &s) {
  const uint16_t value = this->vertical_ ? s.vswing : s.hswing;
  const std::vector<std::string> &options =
      this->vertical_ ? FUJITSU_VSWING_OPTIONS : FUJITSU_HSWING_OPTIONS;
  // 0xFFFF (or any out-of-range value) = the unit does not report this swing.
  if (value < options.size())
    this->publish_state((size_t) value);
}
#endif  // USE_SELECT

// ---------------------------------------------------------------------------
// Light switch
// ---------------------------------------------------------------------------

#ifdef USE_SWITCH
void FujitsuLightSwitch::write_state(bool state) {
  this->parent_->write_light(state);
  this->publish_state(state);
}
#endif  // USE_SWITCH

// ---------------------------------------------------------------------------
// Sensors (10:33 temperature, 10:31 status, 11:01 supported modes)
// ---------------------------------------------------------------------------

void FujitsuACSensor::on_state(const FujitsuACState &state) {
  switch (this->sensor_type_) {
    case FUJITSU_SENSOR_STATUS:
      this->publish_state((float) state.status);
      break;
    case FUJITSU_SENSOR_SUPPORTED_MODES:
      this->publish_state((float) state.supported);
      break;
    case FUJITSU_SENSOR_AC_TEMPERATURE:
    default:
      if (!std::isnan(state.ac_temp))
        this->publish_state(state.ac_temp);
      break;
  }
}

}  // namespace fujitsu_ac
}  // namespace esphome
