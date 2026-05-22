#define SERIAL_RX_BUFFER_SIZE 256

#include <Arduino.h>

// ---------------------------------------------------------------------------
// PWM configuration for "DAC0" channel
// ---------------------------------------------------------------------------
// DAC0 is replaced by a PWM output on Pin 6 (PWMH4 / PWMC channel 4).
// This peripheral is entirely independent of TC2/Ch0 used for the sample-rate
// ISR (TC6_IRQn) and of the system-timer channel (TC0 Ch2 / millis).
//
// PWM carrier: 84 MHz / PWM_PERIOD = ~195 kHz with PWM_PERIOD = 431.
//   - 195 kHz carrier sits ~390× above the 500 Hz Nyquist limit at SR=1000.
//   - A simple RC low-pass filter on Pin 6 reconstructs the analog voltage:
//       R = 1 kΩ, C = 10 nF  →  fc ≈ 16 kHz   (passes signal, kills carrier)
//   - Without this filter the output is a square wave, not an analog signal.
//
// Pin assignment:
//   Pin 6  →  PWM output (DAC0 replacement) — add RC filter to use as analog
//   DAC1   →  true analog output (unchanged), via DACC channel 1
// ---------------------------------------------------------------------------

static const uint8_t  PWM_PIN        = 6;      // PWMH4 — safe, no TC conflict
static const uint32_t PWM_PERIOD     = 431u;   // 84 MHz / 431 ≈ 195 kHz carrier
static const float    PWM_PERIOD_F   = 431.0f;

static const float DAC_VREF      = 3.3f;
static const uint16_t DAC_MAX    = 4095;
static const float MAX_AMPLITUDE = 1.65f;
static const float MAX_DC        = 3.3f;
static const float MAX_FREQ      = 5000.0f;
static const int   MIN_SR        = 100;
static const int   MAX_SR        = 100000;
static const int   CMD_BUF_SIZE  = 64;
static const float ABS_GAIN_MAX  = 20.0f;
static const uint8_t NUM_DACS    = 2;

volatile float g_amp1   = 0.5f;
volatile float g_phase1 = 0.0f;
volatile float g_amp2   = 0.5f;
volatile float g_phase2 = 0.0f;
volatile float g_dc     = 2.0f;
volatile float g_gainMax = 4.0f;

volatile float g_freq1[NUM_DACS]    = {100.0f, 100.0f};
volatile float g_freq2[NUM_DACS]    = {200.0f, 200.0f};
volatile float g_pacc1[NUM_DACS]    = {0.0f, 0.0f};
volatile float g_pacc2[NUM_DACS]    = {0.0f, 0.0f};
volatile float g_paccEnv[NUM_DACS]  = {(float)HALF_PI, (float)HALF_PI};
volatile float g_inc1[NUM_DACS]     = {0.0f, 0.0f};
volatile float g_inc2[NUM_DACS]     = {0.0f, 0.0f};
volatile float g_incEnv[NUM_DACS]   = {0.0f, 0.0f};

volatile int  g_sampleRate = 1000;
volatile bool g_running    = false;

volatile bool     g_dbgEnabled       = false;
volatile float    g_dbgLastV[NUM_DACS]    = {0.0f, 0.0f};
volatile float    g_dbgEnvelope[NUM_DACS] = {0.0f, 0.0f};
volatile float    g_dbgPeakV[NUM_DACS]    = {0.0f, 0.0f};
volatile float    g_dbgTroughV[NUM_DACS]  = {DAC_VREF, DAC_VREF};
volatile uint32_t g_dbgClipHigh[NUM_DACS] = {0, 0};
volatile uint32_t g_dbgClipLow[NUM_DACS]  = {0, 0};
volatile uint32_t g_dbgSamples = 0;
volatile uint32_t g_isrUs      = 0;

float clampAmplitude(float a)  { return constrain(a, 0.0f, MAX_AMPLITUDE); }
float clampDC(float dc)        { return constrain(dc, 0.0f, MAX_DC); }
float clampFreq(float f)       { return constrain(f, 0.0f, MAX_FREQ); }
float degToRad(float d)        { return d * (float)PI / 180.0f; }

static inline void wrapPhase(volatile float &phase) {
    if (phase >  TWO_PI) phase -= TWO_PI;
    if (phase < -TWO_PI) phase += TWO_PI;
}

// ---------------------------------------------------------------------------
// PWM output for channel 0 (Pin 6 / PWMC channel 4)
// Duty cycle spans 0 … PWM_PERIOD, mapping linearly to 0 … DAC_VREF.
// ---------------------------------------------------------------------------
static inline void writePwmDuty(uint32_t duty) {
    // CDTYUPD: update duty cycle on next period boundary (glitch-free)
    PWM->PWM_CH_NUM[4].PWM_CDTYUPD = duty;
}

static inline uint32_t voltageToPwm(float v) {
    uint32_t d = (uint32_t)(v / DAC_VREF * PWM_PERIOD_F + 0.5f);
    if (d > PWM_PERIOD) d = PWM_PERIOD;
    return d;
}

// ---------------------------------------------------------------------------
// DAC1 (true analog) — unchanged from original
// ---------------------------------------------------------------------------
static inline uint16_t voltageToDac(float v) {
    uint16_t dac = (uint16_t)(v / DAC_VREF * (float)DAC_MAX + 0.5f);
    if (dac > DAC_MAX) dac = DAC_MAX;
    return dac;
}

// Write a single value to DACC channel 1.
// TAG mode is kept enabled so we must set bit 12 to target channel 1.
void writeDac1(uint16_t dac1) {
    while (!(DACC->DACC_ISR & DACC_ISR_TXRDY));
    // In TAG+WORD mode the upper half-word carries channel 1 with tag bit set.
    // We write only channel 1; channel 0 (now PWM) is ignored by the DACC.
    uint32_t word = ((uint32_t)(dac1 & 0x0FFFu) << 16) | (1u << 28);
    DACC->DACC_CDR = word;
}

void resetDebugStats() {
    for (uint8_t ch = 0; ch < NUM_DACS; ++ch) {
        g_dbgLastV[ch]    = 0.0f;
        g_dbgEnvelope[ch] = 0.0f;
        g_dbgPeakV[ch]    = 0.0f;
        g_dbgTroughV[ch]  = DAC_VREF;
        g_dbgClipHigh[ch] = 0;
        g_dbgClipLow[ch]  = 0;
    }
    g_dbgSamples = 0;
    g_isrUs      = 0;
}

void recomputeIncrements(uint8_t channel) {
    float sr = (float)g_sampleRate;
    g_inc1[channel]    = TWO_PI * g_freq1[channel] / sr;
    g_inc2[channel]    = TWO_PI * g_freq2[channel] / sr;
    g_incEnv[channel]  = (float)PI * (g_freq2[channel] - g_freq1[channel]) / sr;
    g_pacc1[channel]   = g_phase1;
    g_pacc2[channel]   = g_phase2;
    g_paccEnv[channel] = (float)HALF_PI;
}

void recomputeAllIncrements() {
    for (uint8_t ch = 0; ch < NUM_DACS; ++ch) {
        recomputeIncrements(ch);
    }
}

// ---------------------------------------------------------------------------
// Sample-rate ISR — TC2 Channel 0 (TC6_IRQn), unchanged timer assignment
// ---------------------------------------------------------------------------
void TC6_Handler(void) {
    TC_GetStatus(TC2, 0);

    if (!g_running) {
        // Idle: PWM 50 % (mid-rail) and DAC1 to zero
        writePwmDuty(PWM_PERIOD / 2);
        writeDac1(0);
        return;
    }

    uint32_t t0 = micros();

    // Compute signal for both channels
    float v[NUM_DACS];
    for (uint8_t ch = 0; ch < NUM_DACS; ++ch) {
        g_pacc1[ch]   += g_inc1[ch];
        g_pacc2[ch]   += g_inc2[ch];
        g_paccEnv[ch] += g_incEnv[ch];

        wrapPhase(g_pacc1[ch]);
        wrapPhase(g_pacc2[ch]);
        wrapPhase(g_paccEnv[ch]);

        float denom = sinf(g_paccEnv[ch]);
        float envelope;
        if (fabsf(denom) < 1e-6f) {
            envelope = g_gainMax;
        } else {
            envelope = fabsf(1.0f / denom);
            if (envelope > g_gainMax) envelope = g_gainMax;
        }

        float sines = g_amp1 * sinf(g_pacc1[ch]) + g_amp2 * sinf(g_pacc2[ch]);
        v[ch] = g_dc + envelope * sines;

        if (v[ch] < 0.0f) {
            v[ch] = 0.0f;
            g_dbgClipLow[ch]++;
        }
        if (v[ch] > DAC_VREF) {
            v[ch] = DAC_VREF;
            g_dbgClipHigh[ch]++;
        }

        g_dbgLastV[ch]    = v[ch];
        g_dbgEnvelope[ch] = envelope;
        if (v[ch] > g_dbgPeakV[ch])   g_dbgPeakV[ch]   = v[ch];
        if (v[ch] < g_dbgTroughV[ch]) g_dbgTroughV[ch] = v[ch];
    }

    // Channel 0 → PWM on Pin 6
    writePwmDuty(voltageToPwm(v[0]));

    // Channel 1 → true analog DAC1
    writeDac1(voltageToDac(v[1]));

    g_dbgSamples++;
    g_isrUs = micros() - t0;
}

// ---------------------------------------------------------------------------
// Timer setup — identical to original (TC2 Ch0, TIMER_CLOCK1 = 42 MHz)
// ---------------------------------------------------------------------------
void setupTimer(int sampleRate) {
    sampleRate   = constrain(sampleRate, MIN_SR, MAX_SR);
    g_sampleRate = sampleRate;

    pmc_set_writeprotect(false);
    pmc_enable_periph_clk(TC6_IRQn);

    TC_Configure(
        TC2, 0,
        TC_CMR_WAVE | TC_CMR_WAVSEL_UP_RC | TC_CMR_TCCLKS_TIMER_CLOCK1
    );

    uint32_t rc = 42000000UL / (uint32_t)sampleRate;
    TC_SetRC(TC2, 0, rc);

    TC2->TC_CHANNEL[0].TC_IER = TC_IER_CPCS;
    TC2->TC_CHANNEL[0].TC_IDR = ~TC_IER_CPCS;

    NVIC_EnableIRQ(TC6_IRQn);
    TC_Start(TC2, 0);
}

// ---------------------------------------------------------------------------
// DACC setup — only channel 1 is used now
// ---------------------------------------------------------------------------
void setupDACC() {
    pmc_enable_periph_clk(ID_DACC);
    DACC->DACC_CR = DACC_CR_SWRST;
    DACC->DACC_MR = DACC_MR_TRGEN_DIS
                  | DACC_MR_WORD_WORD
                  | DACC_MR_TAG_EN
                  | DACC_MR_REFRESH(1)
                  | DACC_MR_STARTUP_8
                  | DACC_MR_MAXS;
    // Only channel 1 is needed; channel 0 is now PWM.
    dacc_enable_channel(DACC, 1);
    writeDac1(0);
}

// ---------------------------------------------------------------------------
// PWM peripheral setup — PWMC channel 4, Pin 6 (PWMH4)
//
// PWMC is clocked from the 84 MHz master clock via its own prescaler chain,
// completely independent of TC2 and the system timer.  No shared resources.
//
// Carrier:  84 MHz / PWM_PERIOD = ~195 kHz
// Left-aligned, no dead-time, no sync trigger needed.
// ---------------------------------------------------------------------------
void setupPWM() {
    // Enable PWMC clock
    pmc_enable_periph_clk(ID_PWM);

    // Configure Pin 6 as PWMH4 (peripheral B on PIO_C24)
    PIOC->PIO_PDR  =  PIO_PC24;   // surrender pin to peripheral
    PIOC->PIO_ABSR |= PIO_PC24;   // select peripheral B

    // Disable channel 4 before configuring
    PWM->PWM_DIS = PWM_DIS_CHID4;
    while (PWM->PWM_SR & PWM_SR_CHID4);

    // Clock: MCK / 1 = 84 MHz (CPRE = 0 → MCK, CPRDUPD not needed)
    PWM->PWM_CH_NUM[4].PWM_CMR =
          PWM_CMR_CPRE_MCK        // 84 MHz clock source
        | PWM_CMR_CALG            // left-aligned (clear on compare)
        ;                         // polarity: output high when counter < duty

    // Period and initial duty (mid-rail = 50 %)
    PWM->PWM_CH_NUM[4].PWM_CPRD  = PWM_PERIOD;
    PWM->PWM_CH_NUM[4].PWM_CDTY  = PWM_PERIOD / 2;

    // Enable channel
    PWM->PWM_ENA = PWM_ENA_CHID4;
}

// ---------------------------------------------------------------------------
// Debug output — unchanged from original
// ---------------------------------------------------------------------------
static uint32_t g_lastDbgMs = 0;

void printDebug() {
    if (!g_dbgEnabled) return;
    uint32_t now = millis();
    if (now - g_lastDbgMs < 100) return;
    g_lastDbgMs = now;

    float    lastV0    = g_dbgLastV[0];
    float    lastV1    = g_dbgLastV[1];
    float    env0      = g_dbgEnvelope[0];
    float    env1      = g_dbgEnvelope[1];
    float    peak0     = g_dbgPeakV[0];
    float    peak1     = g_dbgPeakV[1];
    float    trough0   = g_dbgTroughV[0];
    float    trough1   = g_dbgTroughV[1];
    uint32_t clipHi0   = g_dbgClipHigh[0];
    uint32_t clipHi1   = g_dbgClipHigh[1];
    uint32_t clipLo0   = g_dbgClipLow[0];
    uint32_t clipLo1   = g_dbgClipLow[1];
    uint32_t samps     = g_dbgSamples;
    uint32_t isrUs     = g_isrUs;

    g_dbgPeakV[0]    = 0.0f;
    g_dbgPeakV[1]    = 0.0f;
    g_dbgTroughV[0]  = DAC_VREF;
    g_dbgTroughV[1]  = DAC_VREF;
    g_dbgClipHigh[0] = 0;
    g_dbgClipHigh[1] = 0;
    g_dbgClipLow[0]  = 0;
    g_dbgClipLow[1]  = 0;

    Serial.print("{\"dbg\":1");
    Serial.print(",\"v0\":"); Serial.print(lastV0, 4);
    Serial.print(",\"v1\":"); Serial.print(lastV1, 4);
    Serial.print(",\"env0\":"); Serial.print(env0, 4);
    Serial.print(",\"env1\":"); Serial.print(env1, 4);
    Serial.print(",\"peak0\":"); Serial.print(peak0, 4);
    Serial.print(",\"peak1\":"); Serial.print(peak1, 4);
    Serial.print(",\"trough0\":"); Serial.print(trough0, 4);
    Serial.print(",\"trough1\":"); Serial.print(trough1, 4);
    Serial.print(",\"clipHi0\":"); Serial.print(clipHi0);
    Serial.print(",\"clipHi1\":"); Serial.print(clipHi1);
    Serial.print(",\"clipLo0\":"); Serial.print(clipLo0);
    Serial.print(",\"clipLo1\":"); Serial.print(clipLo1);
    Serial.print(",\"samps\":"); Serial.print(samps);
    Serial.print(",\"isrUs\":"); Serial.print(isrUs);
    Serial.print(",\"run\":"); Serial.print(g_running ? 1 : 0);
    Serial.println("}");
}

// ---------------------------------------------------------------------------
// Command processing — unchanged from original
// ---------------------------------------------------------------------------
char g_cmdBuf[CMD_BUF_SIZE];
int  g_cmdIdx = 0;

void setChannelFrequency(uint8_t channel, uint8_t slot, float value) {
    bool wasRunning = g_running;
    g_running = false;
    if (slot == 0) {
        g_freq1[channel] = clampFreq(value);
    } else {
        g_freq2[channel] = clampFreq(value);
    }
    recomputeIncrements(channel);
    g_running = wasRunning;
}

void processCommand(const char *cmd) {
    char  key[8];
    float val;

    if (strncmp(cmd, "START", 5) == 0) {
        g_running = false;
        resetDebugStats();
        recomputeAllIncrements();
        g_running = true;
        Serial.println("OK START");
        return;
    }

    if (strncmp(cmd, "STOP", 4) == 0) {
        g_running = false;
        writePwmDuty(PWM_PERIOD / 2);   // idle: mid-rail
        writeDac1(0);
        Serial.println("OK STOP");
        return;
    }

    if (strncmp(cmd, "STATUS", 6) == 0) {
        Serial.print("{\"status\":1");
        Serial.print(",\"a1\":"); Serial.print(g_amp1, 4);
        Serial.print(",\"p1\":"); Serial.print(g_phase1 * 180.0f / PI, 4);
        Serial.print(",\"a2\":"); Serial.print(g_amp2, 4);
        Serial.print(",\"p2\":"); Serial.print(g_phase2 * 180.0f / PI, 4);
        Serial.print(",\"dac0_f1\":"); Serial.print(g_freq1[0], 4);
        Serial.print(",\"dac0_f2\":"); Serial.print(g_freq2[0], 4);
        Serial.print(",\"dac1_f1\":"); Serial.print(g_freq1[1], 4);
        Serial.print(",\"dac1_f2\":"); Serial.print(g_freq2[1], 4);
        Serial.print(",\"dc\":"); Serial.print(g_dc, 4);
        Serial.print(",\"gm\":"); Serial.print(g_gainMax, 4);
        Serial.print(",\"sr\":"); Serial.print(g_sampleRate);
        Serial.print(",\"run\":"); Serial.print(g_running ? 1 : 0);
        Serial.println("}");
        return;
    }

    if (strncmp(cmd, "DBG ", 4) == 0) {
        const char *arg = cmd + 4;
        if (strncmp(arg, "ON", 2) == 0) {
            g_dbgEnabled = true;
            Serial.println("OK DBG ON");
        } else if (strncmp(arg, "OFF", 3) == 0) {
            g_dbgEnabled = false;
            Serial.println("OK DBG OFF");
        } else {
            Serial.println("ERR DBG ON|OFF");
        }
        return;
    }

    if (sscanf(cmd, "SET %7s %f", key, &val) == 2) {
        if (strcmp(key, "A1") == 0) {
            g_amp1 = clampAmplitude(val);
            Serial.print("OK A1="); Serial.println(g_amp1, 4);
        } else if (strcmp(key, "A2") == 0) {
            g_amp2 = clampAmplitude(val);
            Serial.print("OK A2="); Serial.println(g_amp2, 4);
        } else if (strcmp(key, "P1") == 0) {
            bool wasRunning = g_running;
            g_running = false;
            g_phase1 = degToRad(val);
            recomputeAllIncrements();
            g_running = wasRunning;
            Serial.print("OK P1="); Serial.println(val, 4);
        } else if (strcmp(key, "P2") == 0) {
            bool wasRunning = g_running;
            g_running = false;
            g_phase2 = degToRad(val);
            recomputeAllIncrements();
            g_running = wasRunning;
            Serial.print("OK P2="); Serial.println(val, 4);
        } else if (strcmp(key, "DC") == 0) {
            g_dc = clampDC(val);
            Serial.print("OK DC="); Serial.println(g_dc, 4);
        } else if (strcmp(key, "GM") == 0) {
            if (val < 1.0f)         val = 1.0f;
            if (val > ABS_GAIN_MAX) val = ABS_GAIN_MAX;
            g_gainMax = val;
            Serial.print("OK GM="); Serial.println(g_gainMax, 4);
        } else if (strcmp(key, "SR") == 0) {
            bool wasRunning = g_running;
            g_running = false;
            delay(2);
            setupTimer((int)val);
            recomputeAllIncrements();
            g_running = wasRunning;
            Serial.print("OK SR="); Serial.println(g_sampleRate);
        } else if (strcmp(key, "F1") == 0 || strcmp(key, "D0F1") == 0) {
            setChannelFrequency(0, 0, val);
            Serial.print("OK D0F1="); Serial.println(g_freq1[0], 4);
        } else if (strcmp(key, "F2") == 0 || strcmp(key, "D0F2") == 0) {
            setChannelFrequency(0, 1, val);
            Serial.print("OK D0F2="); Serial.println(g_freq2[0], 4);
        } else if (strcmp(key, "D1F1") == 0) {
            setChannelFrequency(1, 0, val);
            Serial.print("OK D1F1="); Serial.println(g_freq1[1], 4);
        } else if (strcmp(key, "D1F2") == 0) {
            setChannelFrequency(1, 1, val);
            Serial.print("OK D1F2="); Serial.println(g_freq2[1], 4);
        } else {
            Serial.print("ERR unknown key: "); Serial.println(key);
        }
        return;
    }

    Serial.print("ERR bad command: "); Serial.println(cmd);
}

// ---------------------------------------------------------------------------
// setup / loop
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    while (!Serial);

    setupDACC();        // DAC1 true analog
    setupPWM();         // Pin 6 ~195 kHz PWM (DAC0 replacement)
    resetDebugStats();
    recomputeAllIncrements();
    setupTimer(g_sampleRate);   // 1000 Hz sample rate ISR on TC6

    NVIC_SetPriority(UART_IRQn, 0);
    NVIC_SetPriority(TC6_IRQn,  1);
    // PWMC runs autonomously in hardware — no IRQ priority needed
    // PWM_IRQn is not enabled; duty updates are register writes only

    Serial.println("READY dual_dac_sine v4.1 (ch0=PWM pin6, ch1=DAC1)");
}

void loop() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (g_cmdIdx > 0) {
                g_cmdBuf[g_cmdIdx] = '\0';
                processCommand(g_cmdBuf);
                g_cmdIdx = 0;
            }
        } else if (g_cmdIdx < CMD_BUF_SIZE - 1) {
            g_cmdBuf[g_cmdIdx++] = c;
        }
    }

    printDebug();
}
