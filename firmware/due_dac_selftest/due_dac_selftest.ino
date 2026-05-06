/*
  Arduino Due two-channel DAC signal generator.

  Serial commands, 115200 baud, newline ending:
    PING
    SET <dac0_code> <dac1_code>
    GEN <dac|both> <sine|square|triangle|ramp|dc> <freq_hz> <amplitude_vpp> <offset_v> <phase_deg>
    GEN2 <shape0> <freq0> <amp0_vpp> <offset0_v> <phase0_deg> <shape1> <freq1> <amp1_vpp> <offset1_v> <phase1_deg>
    WAVE <dac|both> <sine|square|triangle|ramp> <freq_hz> <low_code> <high_code> [phase_deg]
    ZERO
    MID
    STOP
    STATUS
    HELP

  Arduino Due DAC0/DAC1 are 12-bit outputs. Their real voltage range is not
  0..3.3 V; typical boards output approximately 0.55..2.75 V.
*/

#include <Arduino.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

static const uint16_t DAC_MAX_CODE = 4095;
static const unsigned long BAUD_RATE = 115200;
static const unsigned long WAVE_UPDATE_US = 1000;
static const float TWO_PI_F = 6.28318530718f;
static const float DAC_VMIN = 0.55f;
static const float DAC_VMAX = 2.75f;
static const float MAX_FREQUENCY_HZ = 100.0f;

struct PortBuffer {
  char line[192];
  size_t len;
};

enum WaveType {
  WAVE_OFF,
  WAVE_DC,
  WAVE_SINE,
  WAVE_RAMP,
  WAVE_TRIANGLE,
  WAVE_SQUARE
};

struct WaveConfig {
  WaveType type;
  float frequencyHz;
  uint16_t lowCode;
  uint16_t highCode;
  float phaseDeg;
};

static PortBuffer serialBuffer = {{0}, 0};
static PortBuffer serialUsbBuffer = {{0}, 0};
static uint16_t currentDac0 = 0;
static uint16_t currentDac1 = 0;
static WaveConfig wave0 = {WAVE_OFF, 1.0f, 0, DAC_MAX_CODE, 0.0f};
static WaveConfig wave1 = {WAVE_OFF, 1.0f, 0, DAC_MAX_CODE, 0.0f};
static unsigned long waveStartUs = 0;
static unsigned long lastWaveUpdateUs = 0;

static uint16_t clampDacCode(long value) {
  if (value < 0) {
    return 0;
  }
  if (value > DAC_MAX_CODE) {
    return DAC_MAX_CODE;
  }
  return static_cast<uint16_t>(value);
}

static float codeToVoltage(uint16_t code) {
  return DAC_VMIN + (DAC_VMAX - DAC_VMIN) * (static_cast<float>(code) / static_cast<float>(DAC_MAX_CODE));
}

static uint16_t voltageToCode(float voltage) {
  if (voltage < DAC_VMIN) {
    voltage = DAC_VMIN;
  } else if (voltage > DAC_VMAX) {
    voltage = DAC_VMAX;
  }
  float normalized = (voltage - DAC_VMIN) / (DAC_VMAX - DAC_VMIN);
  return clampDacCode(static_cast<long>(normalized * DAC_MAX_CODE + 0.5f));
}

static void writeDacs(uint16_t dac0, uint16_t dac1) {
  currentDac0 = dac0;
  currentDac1 = dac1;
  analogWrite(DAC0, currentDac0);
  analogWrite(DAC1, currentDac1);
}

static void writeDac(uint8_t dac, uint16_t code) {
  if (dac == 0) {
    currentDac0 = code;
    analogWrite(DAC0, currentDac0);
  } else {
    currentDac1 = code;
    analogWrite(DAC1, currentDac1);
  }
}

static void stopWaves() {
  wave0.type = WAVE_OFF;
  wave1.type = WAVE_OFF;
}

static WaveType parseWaveType(const char *text) {
  if (!strcasecmp(text, "dc")) {
    return WAVE_DC;
  }
  if (!strcasecmp(text, "sine") || !strcasecmp(text, "sin")) {
    return WAVE_SINE;
  }
  if (!strcasecmp(text, "ramp") || !strcasecmp(text, "saw")) {
    return WAVE_RAMP;
  }
  if (!strcasecmp(text, "triangle") || !strcasecmp(text, "tri")) {
    return WAVE_TRIANGLE;
  }
  if (!strcasecmp(text, "square") || !strcasecmp(text, "sq")) {
    return WAVE_SQUARE;
  }
  return WAVE_OFF;
}

static const char *waveTypeName(WaveType type) {
  switch (type) {
    case WAVE_DC:
      return "dc";
    case WAVE_SINE:
      return "sine";
    case WAVE_RAMP:
      return "ramp";
    case WAVE_TRIANGLE:
      return "triangle";
    case WAVE_SQUARE:
      return "square";
    default:
      return "off";
  }
}

static int parseDacSelector(const char *text) {
  if (!strcasecmp(text, "0") || !strcasecmp(text, "dac0")) {
    return 0;
  }
  if (!strcasecmp(text, "1") || !strcasecmp(text, "dac1")) {
    return 1;
  }
  if (!strcasecmp(text, "2") || !strcasecmp(text, "both") || !strcasecmp(text, "all")) {
    return 2;
  }
  return -1;
}

static bool validateFrequency(WaveType type, float frequencyHz) {
  if (type == WAVE_DC) {
    return frequencyHz >= 0.0f && frequencyHz <= MAX_FREQUENCY_HZ;
  }
  return frequencyHz > 0.0f && frequencyHz <= MAX_FREQUENCY_HZ;
}

static bool waveFromVoltage(WaveType type, float frequencyHz, float amplitudeVpp, float offsetV, float phaseDeg, WaveConfig *wave) {
  if (type == WAVE_OFF || !validateFrequency(type, frequencyHz)) {
    return false;
  }
  if (offsetV < DAC_VMIN || offsetV > DAC_VMAX || amplitudeVpp < 0.0f) {
    return false;
  }

  float lowV = offsetV - amplitudeVpp * 0.5f;
  float highV = offsetV + amplitudeVpp * 0.5f;

  if (type == WAVE_DC) {
    lowV = offsetV;
    highV = offsetV;
  }

  if (lowV < DAC_VMIN || highV > DAC_VMAX) {
    return false;
  }

  wave->type = type;
  wave->frequencyHz = frequencyHz;
  wave->lowCode = voltageToCode(lowV);
  wave->highCode = voltageToCode(highV);
  wave->phaseDeg = phaseDeg;
  return true;
}

static uint16_t waveSample(const WaveConfig &wave, unsigned long nowUs) {
  if (wave.type == WAVE_OFF) {
    return 0;
  }
  if (wave.type == WAVE_DC || wave.lowCode == wave.highCode) {
    return wave.lowCode;
  }

  float elapsed = static_cast<float>(nowUs - waveStartUs) / 1000000.0f;
  float phase = elapsed * wave.frequencyHz + wave.phaseDeg / 360.0f;
  phase = phase - floorf(phase);

  float normalized = 0.0f;
  switch (wave.type) {
    case WAVE_SINE:
      normalized = 0.5f + 0.5f * sinf(TWO_PI_F * phase);
      break;
    case WAVE_RAMP:
      normalized = phase;
      break;
    case WAVE_TRIANGLE:
      normalized = phase < 0.5f ? phase * 2.0f : (1.0f - phase) * 2.0f;
      break;
    case WAVE_SQUARE:
      normalized = phase < 0.5f ? 0.0f : 1.0f;
      break;
    default:
      normalized = 0.0f;
      break;
  }

  if (normalized < 0.0f) {
    normalized = 0.0f;
  } else if (normalized > 1.0f) {
    normalized = 1.0f;
  }

  uint16_t low = min(wave.lowCode, wave.highCode);
  uint16_t high = max(wave.lowCode, wave.highCode);
  return static_cast<uint16_t>(low + (high - low) * normalized + 0.5f);
}

static void serviceWaveforms() {
  if (wave0.type == WAVE_OFF && wave1.type == WAVE_OFF) {
    return;
  }

  unsigned long now = micros();
  if (now - lastWaveUpdateUs < WAVE_UPDATE_US) {
    return;
  }
  lastWaveUpdateUs = now;

  if (wave0.type != WAVE_OFF) {
    writeDac(0, waveSample(wave0, now));
  }
  if (wave1.type != WAVE_OFF) {
    writeDac(1, waveSample(wave1, now));
  }
}

static void printSetResponse(Print &out, const char *status) {
  out.print("{\"type\":\"set\",\"status\":\"");
  out.print(status);
  out.print("\",\"dac0\":");
  out.print(currentDac0);
  out.print(",\"dac1\":");
  out.print(currentDac1);
  out.println("}");
}

static void printPong(Print &out) {
  out.println("{\"type\":\"pong\",\"board\":\"Arduino Due\",\"dac_bits\":12,\"dac_vmin\":0.55,\"dac_vmax\":2.75,\"commands\":[\"GEN\",\"GEN2\",\"WAVE\",\"SET\",\"STOP\",\"STATUS\"]}");
}

static void printWaveObject(Print &out, const WaveConfig &wave, int dac) {
  float lowV = codeToVoltage(min(wave.lowCode, wave.highCode));
  float highV = codeToVoltage(max(wave.lowCode, wave.highCode));

  out.print("{\"dac\":");
  out.print(dac);
  out.print(",\"wave\":\"");
  out.print(waveTypeName(wave.type));
  out.print("\",\"frequency_hz\":");
  out.print(wave.frequencyHz, 4);
  out.print(",\"amplitude_vpp\":");
  out.print(highV - lowV, 4);
  out.print(",\"offset_v\":");
  out.print((highV + lowV) * 0.5f, 4);
  out.print(",\"phase_deg\":");
  out.print(wave.phaseDeg, 2);
  out.print(",\"low_code\":");
  out.print(min(wave.lowCode, wave.highCode));
  out.print(",\"high_code\":");
  out.print(max(wave.lowCode, wave.highCode));
  out.print(",\"low_v\":");
  out.print(lowV, 4);
  out.print(",\"high_v\":");
  out.print(highV, 4);
  out.print("}");
}

static void printWaveResponse(Print &out, const WaveConfig &wave, int dac) {
  out.print("{\"type\":\"wave\",\"status\":\"ok\",\"channel\":");
  printWaveObject(out, wave, dac);
  out.println("}");
}

static void printStatus(Print &out) {
  out.print("{\"type\":\"status\",\"dac0_code\":");
  out.print(currentDac0);
  out.print(",\"dac1_code\":");
  out.print(currentDac1);
  out.print(",\"channels\":[");
  printWaveObject(out, wave0, 0);
  out.print(",");
  printWaveObject(out, wave1, 1);
  out.println("]}");
}

static void printError(Print &out, const char *message) {
  out.print("{\"type\":\"error\",\"message\":\"");
  out.print(message);
  out.println("\"}");
}

static void printHelp(Print &out) {
  out.println("{\"type\":\"help\",\"commands\":[\"PING\",\"SET <dac0> <dac1>\",\"GEN <dac|both> <shape> <freq_hz> <amplitude_vpp> <offset_v> <phase_deg>\",\"GEN2 <shape0> <freq0> <amp0_vpp> <offset0_v> <phase0_deg> <shape1> <freq1> <amp1_vpp> <offset1_v> <phase1_deg>\",\"WAVE <dac|both> <shape> <freq_hz> <low_code> <high_code> [phase_deg]\",\"ZERO\",\"MID\",\"STOP\",\"STATUS\",\"HELP\"]}");
}

static bool parseVoltageWave(WaveConfig *wave) {
  char *typeArg = strtok(NULL, " \t\r\n");
  char *freqArg = strtok(NULL, " \t\r\n");
  char *ampArg = strtok(NULL, " \t\r\n");
  char *offsetArg = strtok(NULL, " \t\r\n");
  char *phaseArg = strtok(NULL, " \t\r\n");

  if (typeArg == NULL || freqArg == NULL || ampArg == NULL || offsetArg == NULL || phaseArg == NULL) {
    return false;
  }

  return waveFromVoltage(
      parseWaveType(typeArg),
      atof(freqArg),
      atof(ampArg),
      atof(offsetArg),
      atof(phaseArg),
      wave);
}

static void handleCommand(char *line, Print &out) {
  char *command = strtok(line, " \t\r\n");
  if (command == NULL) {
    return;
  }

  if (!strcasecmp(command, "PING")) {
    printPong(out);
    return;
  }

  if (!strcasecmp(command, "HELP")) {
    printHelp(out);
    return;
  }

  if (!strcasecmp(command, "STATUS")) {
    printStatus(out);
    return;
  }

  if (!strcasecmp(command, "ZERO")) {
    stopWaves();
    writeDacs(0, 0);
    printSetResponse(out, "ok");
    return;
  }

  if (!strcasecmp(command, "MID")) {
    stopWaves();
    writeDacs(2048, 2048);
    printSetResponse(out, "ok");
    return;
  }

  if (!strcasecmp(command, "STOP")) {
    stopWaves();
    printSetResponse(out, "ok");
    return;
  }

  if (!strcasecmp(command, "SET")) {
    char *arg0 = strtok(NULL, " \t\r\n");
    char *arg1 = strtok(NULL, " \t\r\n");
    if (arg0 == NULL || arg1 == NULL) {
      printError(out, "SET requires two DAC codes");
      return;
    }

    stopWaves();
    writeDacs(clampDacCode(strtol(arg0, NULL, 10)), clampDacCode(strtol(arg1, NULL, 10)));
    printSetResponse(out, "ok");
    return;
  }

  if (!strcasecmp(command, "GEN")) {
    char *dacArg = strtok(NULL, " \t\r\n");
    if (dacArg == NULL) {
      printError(out, "GEN requires dac selector");
      return;
    }

    int dac = parseDacSelector(dacArg);
    WaveConfig wave = {WAVE_OFF, 0.0f, 0, 0, 0.0f};
    if (dac < 0 || !parseVoltageWave(&wave)) {
      printError(out, "GEN format: GEN <dac|both> <shape> <freq_hz> <amplitude_vpp> <offset_v> <phase_deg>; voltage must stay within 0.55..2.75 V");
      return;
    }

    waveStartUs = micros();
    lastWaveUpdateUs = 0;
    if (dac == 0 || dac == 2) {
      wave0 = wave;
      printWaveResponse(out, wave0, 0);
    }
    if (dac == 1 || dac == 2) {
      wave1 = wave;
      printWaveResponse(out, wave1, 1);
    }
    return;
  }

  if (!strcasecmp(command, "GEN2")) {
    WaveConfig next0 = {WAVE_OFF, 0.0f, 0, 0, 0.0f};
    WaveConfig next1 = {WAVE_OFF, 0.0f, 0, 0, 0.0f};
    if (!parseVoltageWave(&next0) || !parseVoltageWave(&next1)) {
      printError(out, "GEN2 format: GEN2 <shape0> <freq0> <amp0_vpp> <offset0_v> <phase0_deg> <shape1> <freq1> <amp1_vpp> <offset1_v> <phase1_deg>");
      return;
    }

    wave0 = next0;
    wave1 = next1;
    waveStartUs = micros();
    lastWaveUpdateUs = 0;
    printWaveResponse(out, wave0, 0);
    printWaveResponse(out, wave1, 1);
    return;
  }

  if (!strcasecmp(command, "WAVE")) {
    char *dacArg = strtok(NULL, " \t\r\n");
    char *typeArg = strtok(NULL, " \t\r\n");
    char *freqArg = strtok(NULL, " \t\r\n");
    char *lowArg = strtok(NULL, " \t\r\n");
    char *highArg = strtok(NULL, " \t\r\n");
    char *phaseArg = strtok(NULL, " \t\r\n");

    if (dacArg == NULL || typeArg == NULL || freqArg == NULL || lowArg == NULL || highArg == NULL) {
      printError(out, "WAVE requires dac, type, freq_hz, low, high");
      return;
    }

    int dac = parseDacSelector(dacArg);
    WaveType type = parseWaveType(typeArg);
    float frequencyHz = atof(freqArg);
    uint16_t lowCode = clampDacCode(strtol(lowArg, NULL, 10));
    uint16_t highCode = clampDacCode(strtol(highArg, NULL, 10));
    float phaseDeg = phaseArg ? atof(phaseArg) : 0.0f;

    if (dac < 0 || type == WAVE_OFF || type == WAVE_DC || !validateFrequency(type, frequencyHz)) {
      printError(out, "invalid WAVE arguments");
      return;
    }

    WaveConfig wave = {type, frequencyHz, lowCode, highCode, phaseDeg};
    waveStartUs = micros();
    lastWaveUpdateUs = 0;

    if (dac == 0 || dac == 2) {
      wave0 = wave;
      printWaveResponse(out, wave0, 0);
    }
    if (dac == 1 || dac == 2) {
      wave1 = wave;
      printWaveResponse(out, wave1, 1);
    }
    return;
  }

  printError(out, "unknown command");
}

static void servicePort(Stream &input, Print &output, PortBuffer &buffer) {
  while (input.available() > 0) {
    char ch = static_cast<char>(input.read());
    if (ch == '\n' || ch == '\r') {
      if (buffer.len > 0) {
        buffer.line[buffer.len] = '\0';
        handleCommand(buffer.line, output);
        buffer.len = 0;
      }
      continue;
    }

    if (buffer.len < sizeof(buffer.line) - 1) {
      buffer.line[buffer.len++] = ch;
    } else {
      buffer.len = 0;
      printError(output, "line too long");
    }
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  analogWriteResolution(12);
  pinMode(DAC0, OUTPUT);
  pinMode(DAC1, OUTPUT);
  writeDacs(0, 0);

  Serial.begin(BAUD_RATE);
  SerialUSB.begin(BAUD_RATE);
}

void loop() {
  servicePort(Serial, Serial, serialBuffer);
  servicePort(SerialUSB, SerialUSB, serialUsbBuffer);
  serviceWaveforms();

  static unsigned long lastBlink = 0;
  unsigned long now = millis();
  if (now - lastBlink >= 1000) {
    lastBlink = now;
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
