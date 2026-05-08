/**
 * dual_sine_dac.ino
 * Arduino Due — DAC1 dual-sine wave generator  (v3.0 — envelope, fixed ISR)
 *
 * Formula (envelope-corrected sum):
 *   A(t)  = clamp( |1 / sin(π(f2-f1)t + π/2)| , 0, GAIN_MAX )
 *   V(t)  = DC + A(t)*[A1*sin(2π*f1*t + φ1) + A2*sin(2π*f2*t + φ2)]
 *   out   = clamp(V(t), 0, 3.3V)  →  DAC counts 0–4095
 *
 * Serial protocol (115200 baud, newline-terminated):
 *   SET A1 <float>   — Amplitude 1 in Volts  (0.0 – 1.65)
 *   SET F1 <float>   — Frequency 1 in Hz     (0.0 – 5000.0)
 *   SET P1 <float>   — Phase 1 in degrees    (any float)
 *   SET A2 <float>   — Amplitude 2 in Volts
 *   SET F2 <float>   — Frequency 2 in Hz
 *   SET P2 <float>   — Phase 2 in degrees
 *   SET DC <float>   — DC offset in Volts    (0.0 – 3.3)
 *   SET SR <int>     — Sample rate in Hz     (100 – 100000)
 *   SET GM <float>   — Max envelope gain cap (1.0 – 20.0, default 4.0)
 *   START            — Begin output (resets phase accumulators)
 *   STOP             — Halt output (DAC set to 0)
 *   STATUS           — Print current parameters as JSON
 *   DBG ON|OFF       — Enable/disable periodic debug telemetry (~10 Hz)
 *
 * Changes from v2.0:
 *   • analogWrite(DAC1, …) replaced with direct DACC register write
 *     → ISR execution time drops ~10×, loop() is no longer starved
 *   • Phase accumulator replaces per-tick t*ω multiply
 *     → removes one float multiply + implicit integer→float cast per tick
 *   • recomputeIncrements() called on START / any
 *     → phase is always coherent from t=0 when output starts
 *   • Serial send() flushes input buffer before each command
 *     → stale bytes can't corrupt next response
 *   • DBG telemetry: JSON lines at ~10 Hz when enabled
 */

#include <Arduino.h>

// ── Constants ────────────────────────────────────────────────────────────────
static const float DAC_VREF      = 3.3f;
static const int   DAC_BITS      = 4095;
static const float MAX_AMPLITUDE = 1.65f;
static const float MAX_DC        = 3.3f;
static const float MAX_FREQ      = 5000.0f;
static const int   MIN_SR        = 100;
static const int   MAX_SR        = 100000;
static const int   CMD_BUF_SIZE  = 64;
static const float ABS_GAIN_MAX  = 20.0f;

// ── Parameters (volatile — shared with ISR) ──────────────────────────────────
volatile float g_amp1    = 0.5f;
volatile float g_freq1   = 100.0f;
volatile float g_phase1  = 0.0f;     // radians

volatile float g_amp2    = 0.5f;
volatile float g_freq2   = 200.0f;
volatile float g_phase2  = 0.0f;

volatile float g_dc       = 1.65f;
volatile float g_gainMax  = 4.0f;

volatile int   g_sampleRate = 10000;
volatile bool  g_running    = false;

// ── ISR phase accumulators ───────────────────────────────────────────────────
volatile float g_pacc1   = 0.0f;     // phase accumulator sine 1
volatile float g_pacc2   = 0.0f;     // phase accumulator sine 2
volatile float g_paccEnv = (float)HALF_PI; // phase accumulator envelope denom

volatile float g_inc1    = 0.0f;
volatile float g_inc2    = 0.0f;
volatile float g_incEnv  = 0.0f;

// ── Debug / stats (written by ISR, read by loop) ─────────────────────────────
volatile bool     g_dbgEnabled   = false;
volatile float    g_dbgLastV     = 0.0f;   // most recent output voltage
volatile float    g_dbgEnvelope  = 0.0f;   // most recent envelope gain
volatile float    g_dbgPeakV     = 0.0f;   // rolling peak  (reset each DBG print)
volatile float    g_dbgTroughV   = 3.3f;   // rolling trough
volatile uint32_t g_dbgClipHigh  = 0;      // clamp-to-3.3 count
volatile uint32_t g_dbgClipLow   = 0;      // clamp-to-0 count
volatile uint32_t g_dbgSamples   = 0;      // total samples since START
volatile uint32_t g_isrUs        = 0;      // last ISR wall-time in µs (approx)

// ── Recompute phase increments (call outside ISR, with g_running = false) ────
void recomputeIncrements() {
    float sr    = (float)g_sampleRate;
    g_inc1    = TWO_PI * g_freq1 / sr;
    g_inc2    = TWO_PI * g_freq2 / sr;
    g_incEnv  = (float)PI * (g_freq2 - g_freq1) / sr;
    // Seed accumulators with the configured initial phases
    g_pacc1   = g_phase1;
    g_pacc2   = g_phase2;
    g_paccEnv = (float)HALF_PI;
}

// ── TC6 ISR — runs at g_sampleRate ──────────────────────────────────────────
void TC6_Handler(void) {
    TC_GetStatus(TC2, 0);   // clear interrupt flag

    if (!g_running) {
        // Write 0 via direct DACC register — no HAL overhead
        while (!(DACC->DACC_ISR & DACC_ISR_TXRDY));
        DACC->DACC_CDR = 0;
        return;
    }

    uint32_t t0 = micros();   // debug timing

    // Advance accumulators
    g_pacc1   += g_inc1;
    g_pacc2   += g_inc2;
    g_paccEnv += g_incEnv;

    // Wrap to [-2π, 2π] to prevent float precision drift on long runs
    if (g_pacc1   >  TWO_PI) g_pacc1   -= TWO_PI;
    if (g_pacc1   < -TWO_PI) g_pacc1   += TWO_PI;
    if (g_pacc2   >  TWO_PI) g_pacc2   -= TWO_PI;
    if (g_pacc2   < -TWO_PI) g_pacc2   += TWO_PI;
    if (g_paccEnv >  TWO_PI) g_paccEnv -= TWO_PI;
    if (g_paccEnv < -TWO_PI) g_paccEnv += TWO_PI;

    // Envelope
    float denom = sinf(g_paccEnv);
    float envelope;
    if (fabsf(denom) < 1e-6f) {
        envelope = g_gainMax;
    } else {
        envelope = fabsf(1.0f / denom);
        if (envelope > g_gainMax) envelope = g_gainMax;
    }

    float sines = g_amp1 * sinf(g_pacc1) + g_amp2 * sinf(g_pacc2);
    float v     = g_dc + envelope * sines;

    // Clamp + count clips
    bool clipped = false;
    if (v < 0.0f)     { v = 0.0f;     g_dbgClipLow++;  clipped = true; }
    if (v > DAC_VREF) { v = DAC_VREF; g_dbgClipHigh++; clipped = true; }

    // Direct DACC write — bypasses analogWrite() HAL
    uint16_t dac_val = (uint16_t)((v / DAC_VREF) * (float)DAC_BITS + 0.5f);
    if (dac_val > (uint16_t)DAC_BITS) dac_val = (uint16_t)DAC_BITS;

    while (!(DACC->DACC_ISR & DACC_ISR_TXRDY));
    DACC->DACC_CDR = dac_val;

    // Update debug stats
    g_dbgLastV    = v;
    g_dbgEnvelope = envelope;
    g_dbgSamples++;
    if (v > g_dbgPeakV)   g_dbgPeakV   = v;
    if (v < g_dbgTroughV) g_dbgTroughV = v;

    g_isrUs = micros() - t0;
}

// ── Timer setup ──────────────────────────────────────────────────────────────
void setupTimer(int sampleRate) {
    sampleRate    = constrain(sampleRate, MIN_SR, MAX_SR);
    g_sampleRate  = sampleRate;

    pmc_set_writeprotect(false);
    pmc_enable_periph_clk(TC6_IRQn);

    TC_Configure(TC2, 0,
        TC_CMR_WAVE | TC_CMR_WAVSEL_UP_RC | TC_CMR_TCCLKS_TIMER_CLOCK1);

    // CLOCK1 = MCK/2 = 42 MHz
    uint32_t rc = 42000000UL / (uint32_t)sampleRate;
    TC_SetRC(TC2, 0, rc);

    TC2->TC_CHANNEL[0].TC_IER = TC_IER_CPCS;
    TC2->TC_CHANNEL[0].TC_IDR = ~TC_IER_CPCS;

    NVIC_EnableIRQ(TC6_IRQn);
    TC_Start(TC2, 0);
}

// ── DACC direct init ─────────────────────────────────────────────────────────
void setupDACC() {
    pmc_enable_periph_clk(ID_DACC);
    DACC->DACC_CR  = DACC_CR_SWRST;
    DACC->DACC_MR  = DACC_MR_TRGEN_DIS
                   | DACC_MR_WORD_HALF
                   | DACC_MR_REFRESH(1)
                   | DACC_MR_STARTUP_8
                   | DACC_MR_MAXS;
    dacc_set_channel_selection(DACC, 1);   // DAC1
    dacc_enable_channel(DACC, 1);
}

// ── Clamp helpers ────────────────────────────────────────────────────────────
float clampAmplitude(float a) { return constrain(a, 0.0f, MAX_AMPLITUDE); }
float clampDC(float dc)       { return constrain(dc, 0.0f, MAX_DC); }
float clampFreq(float f)      { return constrain(f, 0.0f, MAX_FREQ); }
float degToRad(float d)       { return d * (float)PI / 180.0f; }

// ── Debug telemetry printer (called from loop, ~10 Hz when enabled) ──────────
static uint32_t g_lastDbgMs = 0;

void printDebug() {
    if (!g_dbgEnabled) return;
    uint32_t now = millis();
    if (now - g_lastDbgMs < 100) return;   // 10 Hz max
    g_lastDbgMs = now;

    // Snapshot rolling stats and reset them atomically-ish
    // (loop() and ISR share these; brief inconsistency is acceptable for debug)
    float   peak    = g_dbgPeakV;
    float   trough  = g_dbgTroughV;
    float   lastV   = g_dbgLastV;
    float   env     = g_dbgEnvelope;
    uint32_t clipHi = g_dbgClipHigh;
    uint32_t clipLo = g_dbgClipLow;
    uint32_t samps  = g_dbgSamples;
    uint32_t isrUs  = g_isrUs;

    g_dbgPeakV    = 0.0f;
    g_dbgTroughV  = 3.3f;
    g_dbgClipHigh = 0;
    g_dbgClipLow  = 0;

    Serial.print("{\"dbg\":1");
    Serial.print(",\"v\":");       Serial.print(lastV, 4);
    Serial.print(",\"env\":");     Serial.print(env, 4);
    Serial.print(",\"peak\":");    Serial.print(peak, 4);
    Serial.print(",\"trough\":"); Serial.print(trough, 4);
    Serial.print(",\"clipHi\":"); Serial.print(clipHi);
    Serial.print(",\"clipLo\":"); Serial.print(clipLo);
    Serial.print(",\"samps\":");  Serial.print(samps);
    Serial.print(",\"isrUs\":");  Serial.print(isrUs);
    Serial.print(",\"run\":");    Serial.print(g_running ? 1 : 0);
    Serial.println("}");
}

// ── Serial command parser ─────────────────────────────────────────────────────
char g_cmdBuf[CMD_BUF_SIZE];
int  g_cmdIdx = 0;

void processCommand(const char* cmd) {
    char  key[8];
    float val;

    // ── START ────────────────────────────────────────────────────────────────
    if (strncmp(cmd, "START", 5) == 0) {
        g_running = false;          // pause ISR while we reset accumulators
        g_dbgPeakV    = 0.0f;
        g_dbgTroughV  = 3.3f;
        g_dbgClipHigh = 0;
        g_dbgClipLow  = 0;
        g_dbgSamples  = 0;
        recomputeIncrements();
        g_running = true;
        Serial.println("OK START");
        return;
    }

    // ── STOP ─────────────────────────────────────────────────────────────────
    if (strncmp(cmd, "STOP", 4) == 0) {
        g_running = false;
        while (!(DACC->DACC_ISR & DACC_ISR_TXRDY));
        DACC->DACC_CDR = 0;
        Serial.println("OK STOP");
        return;
    }

    // ── STATUS ───────────────────────────────────────────────────────────────
    if (strncmp(cmd, "STATUS", 6) == 0) {
        Serial.print("{\"status\":1");
        Serial.print(",\"a1\":");  Serial.print(g_amp1, 4);
        Serial.print(",\"f1\":");  Serial.print(g_freq1, 4);
        Serial.print(",\"p1\":");  Serial.print(g_phase1 * 180.0f / PI, 4);
        Serial.print(",\"a2\":");  Serial.print(g_amp2, 4);
        Serial.print(",\"f2\":");  Serial.print(g_freq2, 4);
        Serial.print(",\"p2\":");  Serial.print(g_phase2 * 180.0f / PI, 4);
        Serial.print(",\"dc\":");  Serial.print(g_dc, 4);
        Serial.print(",\"gm\":");  Serial.print(g_gainMax, 4);
        Serial.print(",\"sr\":");  Serial.print(g_sampleRate);
        Serial.print(",\"run\":"); Serial.print(g_running ? 1 : 0);
        Serial.println("}");
        return;
    }

    // ── DBG ON / OFF ─────────────────────────────────────────────────────────
    if (strncmp(cmd, "DBG ", 4) == 0) {
        const char* arg = cmd + 4;
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

    // ── SET <KEY> <VALUE> ────────────────────────────────────────────────────
    if (sscanf(cmd, "SET %7s %f", key, &val) == 2) {

        if (strcmp(key, "A1") == 0) {
            g_amp1 = clampAmplitude(val);
            Serial.print("OK A1="); Serial.println(g_amp1, 4);

        } else if (strcmp(key, "A2") == 0) {
            g_amp2 = clampAmplitude(val);
            Serial.print("OK A2="); Serial.println(g_amp2, 4);

        } else if (strcmp(key, "F1") == 0) {
            bool was = g_running; g_running = false;
            g_freq1 = clampFreq(val);
            recomputeIncrements();
            g_running = was;
            Serial.print("OK F1="); Serial.println(g_freq1, 4);

        } else if (strcmp(key, "F2") == 0) {
            bool was = g_running; g_running = false;
            g_freq2 = clampFreq(val);
            recomputeIncrements();
            g_running = was;
            Serial.print("OK F2="); Serial.println(g_freq2, 4);

        } else if (strcmp(key, "P1") == 0) {
            bool was = g_running; g_running = false;
            g_phase1 = degToRad(val);
            recomputeIncrements();
            g_running = was;
            Serial.print("OK P1="); Serial.println(val, 4);

        } else if (strcmp(key, "P2") == 0) {
            bool was = g_running; g_running = false;
            g_phase2 = degToRad(val);
            recomputeIncrements();
            g_running = was;
            Serial.print("OK P2="); Serial.println(val, 4);

        } else if (strcmp(key, "DC") == 0) {
            g_dc = clampDC(val);
            Serial.print("OK DC="); Serial.println(g_dc, 4);

        } else if (strcmp(key, "GM") == 0) {
            if (val < 1.0f)          val = 1.0f;
            if (val > ABS_GAIN_MAX)  val = ABS_GAIN_MAX;
            g_gainMax = val;
            Serial.print("OK GM="); Serial.println(g_gainMax, 4);

        } else if (strcmp(key, "SR") == 0) {
            bool was = g_running; g_running = false;
            delay(2);
            setupTimer((int)val);
            recomputeIncrements();
            g_running = was;
            Serial.print("OK SR="); Serial.println(g_sampleRate);

        } else {
            Serial.print("ERR unknown key: "); Serial.println(key);
        }
        return;
    }

    Serial.print("ERR bad command: "); Serial.println(cmd);
}

// ── setup ────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    while (!Serial);

    setupDACC();
    recomputeIncrements();
    setupTimer(g_sampleRate);

    Serial.println("READY dual_sine_dac v3.0 (envelope+fix)");
}

// ── loop ─────────────────────────────────────────────────────────────────────
void loop() {
    // Read serial commands
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (g_cmdIdx > 0) {
                g_cmdBuf[g_cmdIdx] = '\0';
                processCommand(g_cmdBuf);
                g_cmdIdx = 0;
            }
        } else {
            if (g_cmdIdx < CMD_BUF_SIZE - 1)
                g_cmdBuf[g_cmdIdx++] = c;
        }
    }

    // Emit debug telemetry if enabled
    printDebug();
}