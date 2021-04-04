# control a pair of TI SN76489 programmable sound generator ICs
# wiring: base pin on LSB (both chips in parallel)
#         base pin + 8 on left chip /WE
#         base pin + 9 on right chip /WE
#         base pin + 10 on left chip /OE
#         base pin + 11 on right chip /OE
#         both chips' READY disconnected

from rp2 import PIO, asm_pio, StateMachine
from machine import Pin

@asm_pio(set_init=PIO.OUT_LOW)
def _clock_prog():
    set(pins, 1)
    set(pins, 0)

@asm_pio(out_init=(PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_HIGH, PIO.OUT_HIGH, PIO.OUT_LOW, PIO.OUT_LOW), out_shiftdir=PIO.SHIFT_RIGHT, set_init=(PIO.OUT_HIGH, PIO.OUT_HIGH))
def _xfer_prog():
    pull()
    out(pins, 10)[31]
    set(pins, 3)

class Sound:
    BASE_PIN = 0
    CLOCK_PIN = 12
    CLOCK_FREQ = 1_200_000
    LEFT = 0x200
    RIGHT = 0x100

    def __init__(self, base_pin = BASE_PIN, clock_pin = CLOCK_PIN, clock_freq = CLOCK_FREQ):
        self.base_pin = Pin(base_pin)
        self.we_pin = Pin(base_pin + 8)
        self.clock_pin = Pin(clock_pin)
        self.clock_freq = clock_freq

        self._init_clock()
        self._init_xfer()
        self.silence()

    def set_frequency(self, voice, freq):
        channel, voice = self._unpack_voice(voice)
        self._send_byte(channel, 0x80 | (voice << 5) | (freq & 0x0F))
        self._send_byte(channel, freq >> 4)

    def set_attenuation(self, voice, atten):
        channel, voice = self._unpack_voice(voice)
        self._send_byte(channel, 0x90 | (voice << 5) | atten)

    def set_noise(self, voice, noise):
        channel, voice = self._unpack_voice(voice)
        self._send_byte(channel, 0xE0 | noise)

    def silence(self):
        for voice in range(8):
            self.set_attenuation(voice, 15)

    def shutdown(self):
        self.silence()
        self._stop_xfer()
        self._stop_clock()

    def _unpack_voice(self, voice):
        if voice < 4:
            return (Sound.LEFT, voice)
        else:
            return (Sound.RIGHT, voice - 4)

    def _init_clock(self):
        self.clock_sm = StateMachine(0, _clock_prog, freq=self.clock_freq*2, set_base=self.clock_pin)
        self.clock_sm.active(1)

    def _stop_clock(self):
        self.clock_sm.active(0)

    def _init_xfer(self):
        self.xfer_sm = StateMachine(1, _xfer_prog, freq=self.clock_freq, out_base=self.base_pin, set_base=self.we_pin)
        self.xfer_sm.active(1)

    def _stop_xfer(self):
        self.xfer_sm.active(0)

    def _send_byte(self, channel, byte):
        self.xfer_sm.put(channel | byte)

